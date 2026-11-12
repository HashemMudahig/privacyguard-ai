"""Evidence manifest loading and validation."""

from __future__ import annotations

import csv
from pathlib import Path

from ..errors import DatasetError, UnsafePathError
from ..models import parse_timestamp
from ..safety import ensure_within
from .errors import EvidenceManifestError
from .models import (
    SUPPORTED_FORMATS,
    EvidenceFormat,
    EvidenceManifestEntry,
    ManifestIssue,
    ManifestLoadResult,
)

MANIFEST_FILENAME = "evidence_files.csv"
MANIFEST_HEADERS = ("file_id", "file_path", "origin", "captured_at")

_FORMAT_BY_SUFFIX: dict[str, EvidenceFormat] = {
    ".sql": EvidenceFormat.SQL,
    ".json": EvidenceFormat.JSON,
    ".log": EvidenceFormat.LOG,
    ".txt": EvidenceFormat.TXT,
    ".pdf": EvidenceFormat.PDF,
    ".png": EvidenceFormat.PNG,
}

_UNSUPPORTED_REASONS: dict[EvidenceFormat, str] = {
    EvidenceFormat.PDF: "PDF parsing is not implemented in Sprint 2A",
    EvidenceFormat.PNG: "Image/OCR parsing is not implemented in Sprint 2A",
    EvidenceFormat.UNKNOWN: "Unrecognized evidence file extension",
}


def detect_format(file_path: str | Path) -> EvidenceFormat:
    """Classify a file by its extension only.

    File names are not used to infer content, case families or expected values.
    """
    suffix = Path(file_path).suffix.lower()
    return _FORMAT_BY_SUFFIX.get(suffix, EvidenceFormat.UNKNOWN)


def _read_manifest_rows(manifest_path: Path) -> list[dict[str, str]]:
    if not manifest_path.is_file():
        raise DatasetError(f"Evidence manifest not found: {manifest_path}")
    rows: list[dict[str, str]] = []
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        actual = tuple(reader.fieldnames or ())
        if actual != MANIFEST_HEADERS:
            raise EvidenceManifestError(
                f"Unexpected evidence manifest header: {actual!r}; "
                f"expected {MANIFEST_HEADERS!r}"
            )
        for row_number, raw in enumerate(reader, start=1):
            if None in raw:
                raise EvidenceManifestError(
                    f"Evidence manifest row {row_number} has extra values"
                )
            rows.append({key: (value or "").strip() for key, value in raw.items()})
    return rows


def load_evidence_manifest(
    dataset_dir: str | Path,
    *,
    strict: bool = True,
) -> ManifestLoadResult:
    """Load and validate ``dataset/evidence_files.csv``.

    Validation covers unique ``file_id`` values, non-empty and relative paths,
    path traversal, file existence and timezone-aware capture timestamps.
    Unsupported formats are retained as entries with ``is_supported=False`` and
    an explicit reason rather than silently dropped.
    """
    root = Path(dataset_dir).expanduser().resolve()
    manifest_path = root / MANIFEST_FILENAME
    rows = _read_manifest_rows(manifest_path)

    issues: list[ManifestIssue] = []
    entries: list[EvidenceManifestEntry] = []
    seen_ids: set[str] = set()

    for index, raw in enumerate(rows, start=1):
        file_id = raw["file_id"]
        file_path = raw["file_path"]

        if not file_id:
            issues.append(
                ManifestIssue(code="empty_file_id", message=f"Row {index} has an empty file_id")
            )
            continue
        if file_id in seen_ids:
            issues.append(
                ManifestIssue(
                    code="duplicate_file_id",
                    file_id=file_id,
                    file_path=file_path,
                    message=f"Duplicate file_id {file_id!r} at row {index}",
                )
            )
            continue
        seen_ids.add(file_id)

        if not file_path:
            issues.append(
                ManifestIssue(
                    code="empty_file_path",
                    file_id=file_id,
                    message="Empty file_path",
                )
            )
            continue

        relative = Path(file_path)
        if relative.is_absolute():
            issues.append(
                ManifestIssue(
                    code="absolute_path",
                    file_id=file_id,
                    file_path=file_path,
                    message="Absolute evidence paths are not allowed",
                )
            )
            continue

        candidate = (root / relative).resolve()
        try:
            ensure_within(root, candidate)
        except UnsafePathError:
            issues.append(
                ManifestIssue(
                    code="path_traversal",
                    file_id=file_id,
                    file_path=file_path,
                    message="Evidence path escapes the dataset directory",
                )
            )
            continue

        if not candidate.is_file():
            issues.append(
                ManifestIssue(
                    code="missing_file",
                    file_id=file_id,
                    file_path=file_path,
                    message=f"Evidence file does not exist: {file_path}",
                )
            )

        try:
            captured_at = parse_timestamp(raw["captured_at"])
        except Exception as exc:  # noqa: BLE001 - report as manifest issue
            issues.append(
                ManifestIssue(
                    code="invalid_timestamp",
                    file_id=file_id,
                    file_path=file_path,
                    message=f"Invalid captured_at {raw['captured_at']!r}: {exc}",
                )
            )
            continue

        evidence_format = detect_format(relative)
        is_supported = evidence_format in SUPPORTED_FORMATS
        reason = None if is_supported else _UNSUPPORTED_REASONS[evidence_format]
        entries.append(
            EvidenceManifestEntry(
                file_id=file_id,
                file_path=file_path,
                origin=raw["origin"],
                captured_at=captured_at,
                format=evidence_format,
                is_supported=is_supported,
                unsupported_reason=reason,
                resolved_path=candidate,
            )
        )

    if strict and issues:
        detail = "; ".join(f"[{issue.code}] {issue.message}" for issue in issues)
        raise EvidenceManifestError(f"Invalid evidence manifest: {detail}")

    return ManifestLoadResult(
        manifest_path=manifest_path,
        entries=tuple(entries),
        issues=tuple(issues),
    )
