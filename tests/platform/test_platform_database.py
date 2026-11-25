from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from privacyguard.platform.app import create_app
from privacyguard.platform.database import resolve_database_url, validate_database_url
from privacyguard.platform.models import AuditRun


def test_runtime_requires_database_environment(monkeypatch) -> None:
    monkeypatch.delenv("PRIVACYGUARD_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="PRIVACYGUARD_DATABASE_URL"):
        resolve_database_url()


def test_postgres_database_isolation_guard() -> None:
    with pytest.raises(ValueError, match="privacyguard_platform"):
        validate_database_url("postgresql+psycopg://user@localhost/smartshop_test")


def test_explicit_in_memory_sqlite_gets_test_schema() -> None:
    app = create_app("sqlite:///:memory:")
    assert set(inspect(app.state.platform_db.engine).get_table_names()) == {
        "audit_requests",
        "audit_runs",
        "audit_tasks",
        "evidence_records",
        "workspaces",
    }


def test_file_sqlite_is_not_initialized_implicitly(project_tmp_path) -> None:
    database_path = project_tmp_path / "isolated.db"
    app = create_app(f"sqlite:///{database_path.as_posix()}")
    try:
        assert inspect(app.state.platform_db.engine).get_table_names() == []
    finally:
        app.state.platform_db.engine.dispose()


def test_isolated_sqlite_enforces_foreign_keys_and_rollback() -> None:
    app = create_app("sqlite:///:memory:")
    session = app.state.platform_db.session()
    try:
        session.add(
            AuditRun(
                id="invalid-run",
                audit_request_id="missing-request",
                status="PENDING",
                step_count=0,
                created_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert session.get(AuditRun, "invalid-run") is None
    finally:
        session.close()
        app.state.platform_db.dispose()
