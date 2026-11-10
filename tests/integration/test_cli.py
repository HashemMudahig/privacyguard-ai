"""CLI integration tests using the real dataset and project-internal temp dirs."""

from __future__ import annotations

from pathlib import Path

from privacyguard.cli import main
from privacyguard.config import PROJECT_ROOT
from privacyguard.identity.report import summarize_resolutions, write_json_report
from privacyguard.identity.resolver import IdentityResolver


def test_cli_info(settings, capsys) -> None:
    assert main(["info", "--dataset", str(settings.dataset_dir)]) == 0
    output = capsys.readouterr().out
    assert "current identities" in output
    assert "evaluation requests" in output
    assert "850" in output


def test_cli_audit_sample(settings, capsys) -> None:
    assert main(
        ["audit-requests", "--requests", "sample", "--dataset", str(settings.dataset_dir)]
    ) == 0
    output = capsys.readouterr().out
    assert "total requests : 32" in output
    assert "resolved       : 32" in output
    assert "exceptions     : none" in output


def test_cli_resolve_uses_a_real_identity(settings, bundle, capsys) -> None:
    email = bundle.identities.records[0].email
    assert main(
        ["resolve", email, "--kind", "email", "--dataset", str(settings.dataset_dir)]
    ) == 0
    output = capsys.readouterr().out
    assert "status        : RESOLVED" in output
    assert "CURRENT_EMAIL" in output


def test_cli_resolve_unknown_returns_nonzero(settings, capsys) -> None:
    assert main(
        [
            "resolve",
            "definitely-not-present@example.invalid",
            "--dataset",
            str(settings.dataset_dir),
        ]
    ) == 1
    output = capsys.readouterr().out
    assert "NOT_FOUND" in output


def test_json_report_written_inside_project(
    project_tmp_path: Path, bundle, resolver: IdentityResolver
) -> None:
    resolutions = resolver.resolve_requests(bundle.sample_requests)
    summary = summarize_resolutions(
        bundle.dataset_dir, bundle.sample_requests.display_name, resolutions
    )
    target = project_tmp_path / "report.json"
    written = write_json_report(
        target, summary, resolutions, project_root=PROJECT_ROOT
    )
    assert written.is_file()
    content = written.read_text(encoding="utf-8")
    assert '"total_requests": 32' in content
