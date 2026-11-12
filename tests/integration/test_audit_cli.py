"""CLI integration tests for Sprint 2C audit commands."""

from __future__ import annotations

from pathlib import Path

from privacyguard.cli import main


def test_cli_audit_sample(settings, project_tmp_path: Path, capsys) -> None:
    target = project_tmp_path / "sample.csv"
    assert main(
        [
            "audit-sample",
            "--dataset",
            str(settings.dataset_dir),
            "--output",
            str(target),
        ]
    ) == 0
    output = capsys.readouterr().out
    assert "Audit sample cases: 32" in output
    assert "validation  : PASS" in output
    assert target.is_file()


def test_cli_audit_eval(settings, project_tmp_path: Path, capsys) -> None:
    target = project_tmp_path / "eval.csv"
    assert main(
        [
            "audit-eval",
            "--dataset",
            str(settings.dataset_dir),
            "--output",
            str(target),
        ]
    ) == 0
    output = capsys.readouterr().out
    assert "Audit eval cases: 518" in output
    assert "validation  : PASS" in output
    assert target.is_file()


def test_cli_validate_output(settings, project_tmp_path: Path, capsys) -> None:
    target = project_tmp_path / "sample.csv"
    assert main(
        [
            "audit-sample",
            "--dataset",
            str(settings.dataset_dir),
            "--output",
            str(target),
        ]
    ) == 0
    capsys.readouterr()
    assert main(
        [
            "validate-output",
            "--dataset",
            str(settings.dataset_dir),
            "--path",
            str(target),
            "--requests",
            "sample",
        ]
    ) == 0
    output = capsys.readouterr().out
    assert "Validation: PASS" in output
    assert "rows   : 32" in output


def test_cli_evaluate_sample(settings, project_tmp_path: Path, capsys) -> None:
    target = project_tmp_path / "evaluation.json"
    assert main(
        [
            "evaluate-sample",
            "--dataset",
            str(settings.dataset_dir),
            "--json-out",
            str(target),
        ]
    ) == 0
    output = capsys.readouterr().out
    assert "Sample evaluation" in output
    assert "status accuracy" in output
    assert target.is_file()
