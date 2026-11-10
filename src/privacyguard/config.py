"""Runtime configuration.

The dataset is owned by the read-only sibling repository and is never copied
or written to. All paths are configurable through CLI arguments or environment
variables:

- ``PG_DATASET_DIR``: directory containing the challenge CSV files.
- ``PG_REPORTS_DIR``: directory inside this project for optional JSON reports.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import DatasetError

ENV_DATASET_DIR = "PG_DATASET_DIR"
ENV_REPORTS_DIR = "PG_REPORTS_DIR"

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_DIR: Path = (
    PROJECT_ROOT.parent / "hackerrank-orchestrate-october26" / "dataset"
)
DEFAULT_REPORTS_DIR: Path = PROJECT_ROOT / "reports"


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved runtime settings."""

    dataset_dir: Path
    reports_dir: Path

    @classmethod
    def from_environment(
        cls,
        dataset_dir: str | Path | None = None,
        reports_dir: str | Path | None = None,
    ) -> "Settings":
        """Build settings from arguments first, then environment, then defaults."""
        raw_dataset = dataset_dir or os.environ.get(ENV_DATASET_DIR) or DEFAULT_DATASET_DIR
        raw_reports = reports_dir or os.environ.get(ENV_REPORTS_DIR) or DEFAULT_REPORTS_DIR
        return cls(
            dataset_dir=Path(raw_dataset).expanduser().resolve(),
            reports_dir=Path(raw_reports).expanduser().resolve(),
        )

    def require_dataset(self) -> Path:
        """Return the dataset directory or raise a descriptive error."""
        if not self.dataset_dir.is_dir():
            raise DatasetError(
                f"Dataset directory not found: {self.dataset_dir}. "
                f"Set {ENV_DATASET_DIR} or pass --dataset."
            )
        return self.dataset_dir
