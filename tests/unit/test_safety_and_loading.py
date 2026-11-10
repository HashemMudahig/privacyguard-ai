"""Unit tests for write-safety and CSV loading errors."""

from __future__ import annotations

from pathlib import Path

import pytest

from privacyguard.config import PROJECT_ROOT
from privacyguard.errors import DatasetError, UnsafePathError
from privacyguard.io.csv_loader import load_user_identities
from privacyguard.safety import ensure_within


def test_ensure_within_accepts_project_path(project_tmp_path: Path) -> None:
    target = project_tmp_path / "ok.txt"
    assert ensure_within(PROJECT_ROOT, target) == target.resolve()


def test_ensure_within_rejects_outside_path() -> None:
    outside = PROJECT_ROOT.parent / "privacyguard-should-never-write.txt"
    with pytest.raises(UnsafePathError):
        ensure_within(PROJECT_ROOT, outside)
    assert not outside.exists()


def test_loader_rejects_bad_header(project_tmp_path: Path) -> None:
    path = project_tmp_path / "bad.csv"
    path.write_text("wrong,header\n1,2\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="Unexpected header"):
        load_user_identities(path, display_name="bad.csv")


def test_loader_rejects_missing_file(project_tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="missing"):
        load_user_identities(project_tmp_path / "absent.csv")
