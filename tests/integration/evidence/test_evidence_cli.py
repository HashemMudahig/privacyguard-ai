"""CLI integration tests for evidence commands."""

from __future__ import annotations

from pathlib import Path

from privacyguard.cli import main
from privacyguard.config import PROJECT_ROOT


def test_evidence_inventory_cli(settings, capsys) -> None:
    assert main(
        ["evidence", "inventory", "--dataset", str(settings.dataset_dir)]
    ) == 0
    output = capsys.readouterr().out
    assert "entries              : 94" in output
    assert "supported entries    : 79" in output
    assert "unsupported entries  : 15" in output
    assert "observations         : 3469" in output
    assert "parse failures" not in output


def test_evidence_inspect_cli(settings, capsys) -> None:
    assert main(
        [
            "evidence",
            "inspect",
            "--file-id",
            "evidence_03",
            "--limit",
            "3",
            "--dataset",
            str(settings.dataset_dir),
        ]
    ) == 0
    output = capsys.readouterr().out
    assert "observations: 41" in output
    assert "account_service" in output
    assert "USER_PROFILE" in output


def test_evidence_inspect_unsupported(settings, capsys) -> None:
    assert main(
        [
            "evidence",
            "inspect",
            "--file-id",
            "evidence_04",
            "--dataset",
            str(settings.dataset_dir),
        ]
    ) == 1
    output = capsys.readouterr().out
    assert "unsupported" in output.lower()


def test_evidence_for_user_cli(settings, bundle, capsys) -> None:
    email = bundle.identities.records[0].email
    assert main(
        [
            "evidence",
            "for-user",
            "--email",
            email,
            "--dataset",
            str(settings.dataset_dir),
        ]
    ) == 0
    output = capsys.readouterr().out
    assert "Evidence for resolved identity" in output
    assert "user_id" in output


def test_evidence_inventory_json_inside_project(
    settings, project_tmp_path: Path, capsys
) -> None:
    target = project_tmp_path / "inventory.json"
    assert main(
        [
            "evidence",
            "inventory",
            "--dataset",
            str(settings.dataset_dir),
            "--json-out",
            str(target),
        ]
    ) == 0
    capsys.readouterr()
    assert target.is_file()
    content = target.read_text(encoding="utf-8")
    assert '"total_entries": 94' in content
    assert '"observation_count": 3469' in content


def test_evidence_inventory_refuses_outside_write(settings, capsys) -> None:
    target = PROJECT_ROOT.parent / "privacyguard-forbidden-evidence-inventory.json"
    assert main(
        [
            "evidence",
            "inventory",
            "--dataset",
            str(settings.dataset_dir),
            "--json-out",
            str(target),
        ]
    ) == 2
    assert not target.exists()
    capsys.readouterr()
