"""Generic containers for loaded dataset rows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class LoadedRow(Generic[T]):
    """One validated row plus its 1-based data-row position and raw values."""

    row_number: int
    record: T
    raw: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class DatasetFile(Generic[T]):
    """A validated CSV file with stable ordering and provenance metadata."""

    path: Path
    display_name: str
    rows: tuple[LoadedRow[T], ...]

    @property
    def records(self) -> tuple[T, ...]:
        return tuple(row.record for row in self.rows)

    def __len__(self) -> int:
        return len(self.rows)
