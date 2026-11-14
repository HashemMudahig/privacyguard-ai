"""Local OCR engine integration.

The baseline uses the OCR engine built into Windows 10/11 through PowerShell.
No text, image, or extracted content is transmitted to an external service.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class OcrError(Exception):
    """Base OCR error."""


class OcrUnavailableError(OcrError):
    """Raised when no local OCR engine is available."""


class OcrExtractionError(OcrError):
    """Raised when a local OCR engine fails on an image."""


@dataclass(frozen=True, slots=True)
class OcrWord:
    text: str
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class OcrLine:
    text: str
    words: tuple[OcrWord, ...]

    @property
    def bounds(self) -> tuple[int, int, int, int] | None:
        if not self.words:
            return None
        x = min(word.x for word in self.words)
        y = min(word.y for word in self.words)
        right = max(word.x + word.width for word in self.words)
        bottom = max(word.y + word.height for word in self.words)
        return (x, y, right - x, bottom - y)


@dataclass(frozen=True, slots=True)
class OcrResult:
    width: int
    height: int
    lines: tuple[OcrLine, ...]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


_CACHE: dict[tuple[str, int, int], OcrResult] = {}


class WindowsOcrEngine:
    """Invoke the built-in Windows OCR engine through a bundled PowerShell script."""

    def __init__(self, script_path: Path | None = None, timeout: int = 60) -> None:
        self.script_path = script_path or Path(__file__).with_name("windows_ocr.ps1")
        self.timeout = timeout

    def available(self) -> bool:
        return (
            platform.system().lower() == "windows"
            and shutil.which("powershell") is not None
            and self.script_path.is_file()
        )

    def extract(self, image_path: str | Path) -> OcrResult:
        if not self.available():
            raise OcrUnavailableError(
                "Windows OCR engine is unavailable (requires Windows PowerShell and the bundled script)"
            )
        path = Path(image_path).resolve()
        try:
            stat = path.stat()
        except OSError as exc:
            raise OcrExtractionError(f"Cannot stat image: {exc}") from exc
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        if key in _CACHE:
            return _CACHE[key]

        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.script_path),
            str(path),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OcrExtractionError(f"OCR process failed: {exc}") from exc
        if completed.returncode != 0:
            raise OcrExtractionError(
                f"OCR process exited with {completed.returncode}: "
                f"{(completed.stderr or completed.stdout or '').strip()[:300]}"
            )
        payload_text = _extract_json(completed.stdout)
        if not payload_text:
            raise OcrExtractionError("OCR process returned no JSON payload")
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise OcrExtractionError(f"OCR JSON could not be parsed: {exc}") from exc
        result = _parse_payload(payload)
        _CACHE[key] = result
        return result


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return ""
    return text[start : end + 1]


def _parse_payload(payload: Any) -> OcrResult:
    if not isinstance(payload, dict):
        raise OcrExtractionError("OCR payload is not an object")
    width = int(payload.get("width", 0))
    height = int(payload.get("height", 0))
    lines: list[OcrLine] = []
    for raw_line in payload.get("lines", []):
        if not isinstance(raw_line, dict):
            continue
        words: list[OcrWord] = []
        for raw_word in raw_line.get("words", []):
            if not isinstance(raw_word, dict):
                continue
            text = str(raw_word.get("text", ""))
            if not text:
                continue
            words.append(
                OcrWord(
                    text=text,
                    x=int(raw_word.get("x", 0)),
                    y=int(raw_word.get("y", 0)),
                    width=int(raw_word.get("w", 0)),
                    height=int(raw_word.get("h", 0)),
                )
            )
        text = str(raw_line.get("text", "")).strip()
        if text or words:
            lines.append(OcrLine(text=text or " ".join(word.text for word in words), words=tuple(words)))
    return OcrResult(width=width, height=height, lines=tuple(lines))
