"""Opt-in tests that write only synthetic records to privacyguard_platform.

Run only after read-only discovery, explicit approval, provisioning, and Alembic
migration. The fixture deletes only its UUID-namespaced synthetic workspace.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from privacyguard.platform.app import create_app
from privacyguard.platform.database import PlatformDatabase, validate_database_url
from privacyguard.platform.models import AuditRequest, AuditRun, Workspace
from privacyguard.platform.service import AuditOutcome

RUN_LIVE = os.getenv("PRIVACYGUARD_RUN_POSTGRES_TESTS") == "1"
pytestmark = pytest.mark.skipif(
    not RUN_LIVE,
    reason="set PRIVACYGUARD_RUN_POSTGRES_TESTS=1 for approved PostgreSQL writes",
)


class SyntheticAuditRunner:
    def run(self, audit_request) -> AuditOutcome:
        return AuditOutcome(
            status="COMPLETE",
            step_count=1,
            evidence_ids=("postgres-integration-evidence",),
        )


@pytest.fixture(scope="module")
def postgres_url() -> str:
    url = os.getenv("PRIVACYGUARD_TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "PRIVACYGUARD_TEST_DATABASE_URL is required when live tests are enabled"
        )
    return validate_database_url(url)


@pytest.fixture()
def synthetic_workspace(postgres_url: str):
    workspace_id = f"pg-it-{uuid.uuid4()}"
    yield workspace_id
    database = PlatformDatabase(postgres_url)
    try:
        with database.session_factory.begin() as session:
            workspace = session.get(Workspace, workspace_id)
            if workspace is not None:
                session.delete(workspace)
    finally:
        database.dispose()


def test_postgresql_connection_and_alembic_schema(postgres_url: str) -> None:
    database = PlatformDatabase(postgres_url)
    try:
        with database.engine.connect() as connection:
            assert connection.execute(
                text("SELECT current_database()")
            ).scalar_one() == "privacyguard_platform"
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "2091eaa64392"
            assert set(inspect(connection).get_table_names()).issuperset(
                {
                    "workspaces",
                    "audit_requests",
                    "audit_runs",
                    "evidence_records",
                    "audit_tasks",
                }
            )
    finally:
        database.dispose()


def test_postgresql_api_persistence_constraints_and_relationships(
    postgres_url: str,
    synthetic_workspace: str,
) -> None:
    app = create_app(postgres_url, audit_runner=SyntheticAuditRunner())
    with TestClient(app) as client:
        workspace_response = client.post(
            "/api/v1/workspaces",
            json={"id": synthetic_workspace, "name": "PostgreSQL integration"},
        )
        assert workspace_response.status_code == 201
        duplicate = client.post(
            "/api/v1/workspaces",
            json={"id": synthetic_workspace, "name": "Duplicate"},
        )
        assert duplicate.status_code == 409
        request_response = client.post(
            f"/api/v1/audit-requests?workspace_id={synthetic_workspace}",
            json={
                "request_id": "REQ-PG-INTEGRATION",
                "email": "synthetic@example.invalid",
                "audit_at": "2026-03-10T00:00:00Z",
                "request_text": "Synthetic integration request",
            },
        )
        assert request_response.status_code == 201
        request_id = request_response.json()["id"]
        run_response = client.post(f"/api/v1/audit-requests/{request_id}/runs")
        assert run_response.status_code == 201
        run_id = run_response.json()["id"]

    restarted_app = create_app(postgres_url, audit_runner=SyntheticAuditRunner())
    with TestClient(restarted_app) as restarted_client:
        assert restarted_client.get(
            f"/api/v1/audit-requests/{request_id}"
        ).status_code == 200
        persisted_run = restarted_client.get(f"/api/v1/audit-runs/{run_id}")
        assert persisted_run.status_code == 200
        assert persisted_run.json()["status"] == "COMPLETED"
        assert persisted_run.json()["verification_status"] == "COMPLETE"

    database = PlatformDatabase(postgres_url)
    try:
        session = database.session()
        try:
            run = session.get(AuditRun, run_id)
            assert run is not None
            assert len(run.evidence_records) == 1
            assert len(run.tasks) == 1
            invalid = AuditRequest(
                id=str(uuid.uuid4()),
                workspace_id="missing-workspace",
                request_id="REQ-INVALID-FK",
                email="synthetic@example.invalid",
                audit_at=run.created_at,
                request_text="Must roll back",
                created_at=run.created_at,
            )
            invalid_id = invalid.id
            session.add(invalid)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
            assert session.get(AuditRequest, invalid_id) is None
        finally:
            session.close()
    finally:
        database.dispose()
