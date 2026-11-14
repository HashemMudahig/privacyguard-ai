"""Local OCR package."""

from .engine import (
    OcrError,
    OcrExtractionError,
    OcrLine,
    OcrResult,
    OcrUnavailableError,
    OcrWord,
    WindowsOcrEngine,
)

__all__ = [
    "OcrError",
    "OcrExtractionError",
    "OcrLine",
    "OcrResult",
    "OcrUnavailableError",
    "OcrWord",
    "WindowsOcrEngine",
]
