from __future__ import annotations

import os
from pathlib import Path

import pytest

from privacyguard.smartshop import db, seed

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "src" / "privacyguard" / "smartshop" / "schema.sql"


def test_schema_file_exists_and_declares_tables() -> None:
    text = SCHEMA.read_text(encoding="utf-8")
    required = {
        "smartshop.customers",
        "smartshop.customer_emails",
        "smartshop.orders",
        "smartshop.invoices",
        "smartshop.support_tickets",
        "smartshop.support_attachments",
        "smartshop.marketing_contacts",
        "smartshop.deletion_requests",
        "smartshop.deletion_activity",
        "smartshop.backup_inventory",
        "smartshop.sync_events",
    }
    for table in required:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in text


def test_schema_uses_foreign_keys_and_safety_indexes() -> None:
    text = SCHEMA.read_text(encoding="utf-8")
    assert "REFERENCES smartshop.customers(customer_id)" in text
    assert "REFERENCES smartshop.orders(order_id)" in text
    assert "REFERENCES smartshop.support_tickets(ticket_id)" in text
    assert "CREATE INDEX" in text


def test_seed_is_deterministic() -> None:
    first = seed.seeded_customers()
    second = seed.seeded_customers()
    assert [customer["customer_id"] for customer in first] == [
        customer["customer_id"] for customer in second
    ]
    assert [customer["primary_email"] for customer in first] == [
        customer["primary_email"] for customer in second
    ]


def test_seed_has_six_core_scenarios() -> None:
    customers = seed.seeded_customers()
    ids = [customer["customer_id"] for customer in customers]
    assert len(ids) == 6
    assert len(set(ids)) == 6
    for customer in customers:
        assert customer["primary_email"].endswith(("@example.com", "@example.net", "@example.org"))
        assert customer["scenario"]


def test_seed_has_no_personal_data_markers() -> None:
    customers = seed.seeded_customers()
    for customer in customers:
        assert "gmail.com" not in str(customer["primary_email"])
        assert "@" in str(customer["primary_email"])


def test_db_refuses_non_test_database_name() -> None:
    os.environ["SMARTSHOP_TEST_MODE"] = "1"
    os.environ["SMARTSHOP_PG_HOST"] = "localhost"
    os.environ["SMARTSHOP_PG_USER"] = "tester"
    os.environ["SMARTSHOP_PG_PASSWORD"] = "placeholder"
    os.environ["SMARTSHOP_PG_DATABASE"] = "production_db"
    with pytest.raises(db.UnsafeSmartShopDatabaseError):
        db.settings_from_env()


def test_db_requires_test_mode() -> None:
    os.environ["SMARTSHOP_TEST_MODE"] = "0"
    os.environ["SMARTSHOP_PG_HOST"] = "localhost"
    os.environ["SMARTSHOP_PG_USER"] = "tester"
    os.environ["SMARTSHOP_PG_PASSWORD"] = "placeholder"
    os.environ["SMARTSHOP_PG_DATABASE"] = "smartshop_test"
    with pytest.raises(db.UnsafeSmartShopDatabaseError):
        db.settings_from_env()

    os.environ["SMARTSHOP_TEST_MODE"] = "1"
    cfg = db.settings_from_env()
    assert cfg["database"] == "smartshop_test"

    for name in ("SMARTSHOP_TEST_MODE", "SMARTSHOP_PG_HOST", "SMARTSHOP_PG_USER",
                 "SMARTSHOP_PG_PASSWORD", "SMARTSHOP_PG_DATABASE"):
        os.environ.pop(name, None)


def test_live_database_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SMARTSHOP_PG_HOST", raising=False)
    with pytest.raises(db.UnsafeSmartShopDatabaseError):
        db.settings_from_env()


def test_seed_sql_is_atomic_and_non_destructive_by_default() -> None:
    sql = seed.seed_sql()
    assert sql.startswith("BEGIN;")
    assert sql.endswith("COMMIT;\n")
    assert "TRUNCATE" not in sql
    assert "ON CONFLICT DO NOTHING" in sql


def test_seed_sql_reset_requires_explicit_flag() -> None:
    sql = seed.seed_sql(allow_reset=True)
    assert "TRUNCATE" in sql
    assert "ON CONFLICT DO NOTHING" not in sql


def test_psql_command_uses_safety_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMARTSHOP_TEST_MODE", "1")
    monkeypatch.setenv("SMARTSHOP_PG_HOST", "localhost")
    monkeypatch.setenv("SMARTSHOP_PG_USER", "tester")
    monkeypatch.setenv("SMARTSHOP_PG_PASSWORD", "placeholder")
    monkeypatch.setenv("SMARTSHOP_PG_DATABASE", "smartshop_test")
    command = db.psql_command(sql="SELECT 1;")
    joined = " ".join(command)
    assert "-X" in command
    assert "ON_ERROR_STOP=1" in joined
