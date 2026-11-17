from __future__ import annotations

import os

import pytest

from privacyguard.smartshop import db, live_setup


def _env_values() -> tuple[str, ...]:
    return (
        "SMARTSHOP_TEST_MODE",
        "SMARTSHOP_PG_HOST",
        "SMARTSHOP_PG_USER",
        "SMARTSHOP_PG_PASSWORD",
        "SMARTSHOP_PG_DATABASE",
    )


def _configured() -> bool:
    return all(os.environ.get(key) for key in _env_values())


def _require_configured() -> None:
    if not _configured():
        pytest.skip("SmartShop PostgreSQL credentials are not configured.")


def test_live_database_target_is_smartshop_test() -> None:
    _require_configured()
    result = db.run_psql("SELECT current_database();")
    assert result.returncode == 0, result.stderr
    assert "smartshop_test" in result.stdout


def test_live_smartshop_schema_and_tables() -> None:
    _require_configured()
    result = db.run_psql(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='smartshop' ORDER BY table_name;",
    )
    assert result.returncode == 0, result.stderr
    expected = {
        "backup_inventory", "customer_emails", "customers", "deletion_activity",
        "deletion_requests", "invoices", "marketing_contacts", "orders",
        "support_attachments", "support_tickets", "sync_events",
    }
    actual = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    assert expected.issubset(actual)


def test_live_smartshop_synthetic_requests_exist() -> None:
    _require_configured()
    result = db.run_psql(
        "SELECT request_id FROM smartshop.deletion_requests WHERE request_id IN "
        "('REQ-0001','REQ-0002','REQ-0003','REQ-0004','REQ-0005','REQ-0006') "
        "ORDER BY request_id;",
    )
    assert result.returncode == 0, result.stderr
    for req in ("REQ-0001", "REQ-0002", "REQ-0003", "REQ-0004", "REQ-0005", "REQ-0006"):
        assert req in result.stdout


def test_live_smartshop_reader_is_read_only() -> None:
    _require_configured()
    result = db.run_psql(
        "SELECT privilege_type FROM information_schema.role_table_grants "
        "WHERE grantee = current_user AND table_schema = 'smartshop' "
        "GROUP BY privilege_type ORDER BY privilege_type;",
    )
    assert result.returncode == 0, result.stderr
    privileges = " ".join(result.stdout.split())
    assert "INSERT" not in privileges
    assert "UPDATE" not in privileges
    assert "DELETE" not in privileges


def test_live_smartshop_audits_all_six_requests() -> None:
    _require_configured()
    from privacyguard.smartshop import audit as audit_mod

    for request_id in ("REQ-0001", "REQ-0002", "REQ-0003", "REQ-0004", "REQ-0005", "REQ-0006"):
        result = audit_mod.audit_smartshop_request(request_id, rules_path=None)
        assert result.case_id == request_id
        assert result.deletion_status is not None
        assert len(result.steps) >= 0
        assert result.status_reasons
