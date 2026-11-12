"""Unit tests for manifest validation using synthetic manifests."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from privacyguard.evidence.errors import EvidenceManifestError
from privacyguard.evidence.manifest import load_evidence_manifest
from privacyguard.evidence.models import EvidenceFormat


def _make_dataset(root: Path) -> Path:
    dataset = root / "dataset"
    (dataset / "evidence").mkdir(parents=True)
    return dataset


def _write_manifest(dataset: Path, rows: list[dict[str, str]]) -> Path:
    path = dataset / "evidence_files.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["file_id", "file_path", "origin", "captured_at"]
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def _row(file_id: str, file_path: str, captured_at: str = "2026-01-01T00:00:00Z") -> dict[str, str]:
    return {
        "file_id": file_id,
        "file_path": file_path,
        "origin": "test",
        "captured_at": captured_at,
    }


def test_valid_manifest_and_unsupported_format(project_tmp_path: Path) -> None:
    dataset = _make_dataset(project_tmp_path)
    (dataset / "evidence" / "a.sql").write_text("SELECT 1;", encoding="utf-8")
    (dataset / "evidence" / "b.png").write_text("not really a png", encoding="utf-8")
    _write_manifest(
        dataset,
        [_row("ev_1", "evidence/a.sql"), _row("ev_2", "evidence/b.png")],
    )

    result = load_evidence_manifest(dataset)
    assert len(result.entries) == 2
    assert result.issues == ()
    sql_entry, png_entry = result.entries
    assert sql_entry.format == EvidenceFormat.SQL
    assert sql_entry.is_supported is True
    assert png_entry.format == EvidenceFormat.PNG
    assert png_entry.is_supported is False
    assert png_entry.unsupported_reason
    assert sql_entry.captured_at.tzinfo is not None


def test_duplicate_file_id_rejected(project_tmp_path: Path) -> None:
    dataset = _make_dataset(project_tmp_path)
    (dataset / "evidence" / "a.sql").write_text("SELECT 1;", encoding="utf-8")
    _write_manifest(
        dataset,
        [_row("ev_1", "evidence/a.sql"), _row("ev_1", "evidence/a.sql")],
    )
    with pytest.raises(EvidenceManifestError, match="duplicate_file_id"):
        load_evidence_manifest(dataset)


def test_path_traversal_rejected(project_tmp_path: Path) -> None:
    dataset = _make_dataset(project_tmp_path)
    outside = project_tmp_path / "outside.sql"
    outside.write_text("SELECT 1;", encoding="utf-8")
    _write_manifest(dataset, [_row("ev_1", "../outside.sql")])
    with pytest.raises(EvidenceManifestError, match="path_traversal"):
        load_evidence_manifest(dataset)


def test_absolute_path_rejected(project_tmp_path: Path) -> None:
    dataset = _make_dataset(project_tmp_path)
    target = project_tmp_path / "absolute.sql"
    target.write_text("SELECT 1;", encoding="utf-8")
    _write_manifest(dataset, [_row("ev_1", str(target))])
    with pytest.raises(EvidenceManifestError, match="absolute_path"):
        load_evidence_manifest(dataset)


def test_missing_file_rejected(project_tmp_path: Path) -> None:
    dataset = _make_dataset(project_tmp_path)
    _write_manifest(dataset, [_row("ev_1", "evidence/missing.sql")])
    with pytest.raises(EvidenceManifestError, match="missing_file"):
        load_evidence_manifest(dataset)


def test_invalid_timestamp_rejected(project_tmp_path: Path) -> None:
    dataset = _make_dataset(project_tmp_path)
    (dataset / "evidence" / "a.sql").write_text("SELECT 1;", encoding="utf-8")
    _write_manifest(dataset, [_row("ev_1", "evidence/a.sql", "not-a-time")])
    with pytest.raises(EvidenceManifestError, match="invalid_timestamp"):
        load_evidence_manifest(dataset)


def test_non_strict_mode_returns_issues(project_tmp_path: Path) -> None:
    dataset = _make_dataset(project_tmp_path)
    _write_manifest(dataset, [_row("ev_1", "evidence/missing.sql")])
    result = load_evidence_manifest(dataset, strict=False)
    assert len(result.entries) == 1
    assert result.entries[0].file_id == "ev_1"
    assert [issue.code for issue in result.issues] == ["missing_file"]
