"""CLI integration tests for inspect-case."""

from __future__ import annotations

import json
from pathlib import Path

from privacyguard.cli import main
from privacyguard.config import PROJECT_ROOT


def test_inspect_case_cli(settings, capsys) -> None:
    assert main(
        [
            "inspect-case",
            "--case-id",
            "case_03",
            "--requests",
            "sample",
            "--dataset",
            str(settings.dataset_dir),
        ]
    ) == 0
    output = capsys.readouterr().out
    assert "Audit context" in output
    assert "case_id        : case_03" in output
    assert "linked_resources:" in output
    assert "states         :" in output


def test_inspect_case_json_inside_project(
    settings, project_tmp_path: Path, capsys
) -> None:
    target = project_tmp_path / "case_03.json"
    assert main(
        [
            "inspect-case",
            "--case-id",
            "case_03",
            "--requests",
            "sample",
            "--dataset",
            str(settings.dataset_dir),
            "--json-out",
            str(target),
        ]
    ) == 0
    capsys.readouterr()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["case_id"] == "case_03"
    assert "states" in payload
    assert "relevant_observations" in payload


def test_inspect_case_refuses_outside_write(settings, capsys) -> None:
    target = PROJECT_ROOT.parent / "privacyguard-forbidden-context.json"
    assert main(
        [
            "inspect-case",
            "--case-id",
            "case_03",
            "--requests",
            "sample",
            "--dataset",
            str(settings.dataset_dir),
            "--json-out",
            str(target),
        ]
    ) == 2
    assert not target.exists()
    capsys.readouterr()


def test_inspect_case_unknown_case(settings, capsys) -> None:
    assert main(
        [
            "inspect-case",
            "--case-id",
            "case_99999",
            "--dataset",
            str(settings.dataset_dir),
        ]
    ) == 2
    assert "Unknown case_id" in capsys.readouterr().err


def test_inspect_case_wrong_request_file(settings, capsys) -> None:
    assert main(
        [
            "inspect-case",
            "--case-id",
            "case_03",
            "--requests",
            "eval",
            "--dataset",
            str(settings.dataset_dir),
        ]
    ) == 2
    assert "belongs to" in capsys.readouterr().err
