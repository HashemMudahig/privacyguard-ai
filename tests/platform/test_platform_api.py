from fastapi.testclient import TestClient

from privacyguard.platform.app import create_app
from privacyguard.platform.models import AuditRun
from privacyguard.platform.service import AuditOutcome


class SyntheticAuditRunner:
    def run(self, audit_request) -> AuditOutcome:
        return AuditOutcome(
            status="INCOMPLETE",
            step_count=2,
            evidence_ids=("synthetic-evidence-1",),
            summary="synthetic test outcome",
        )


def _request_payload(request_id: str = "REQ-0001") -> dict[str, str]:
    return {
        "request_id": request_id,
        "email": "ava@example.com",
        "audit_at": "2026-03-10T00:00:00Z",
        "request_text": "Delete my account",
    }


def test_health_live_and_ready() -> None:
    with TestClient(create_app("sqlite:///:memory:")) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200


def test_workspace_and_audit_request_flow() -> None:
    app = create_app("sqlite:///:memory:", audit_runner=SyntheticAuditRunner())
    with TestClient(app) as client:
        create = client.post(
            "/api/v1/workspaces",
            json={"id": "w1", "name": "SmartShop"},
        )
        assert create.status_code == 201
        request_response = client.post(
            "/api/v1/audit-requests?workspace_id=w1",
            json=_request_payload(),
        )
        assert request_response.status_code == 201
        request_body = request_response.json()
        assert request_body["request_id"] == "REQ-0001"

        run_response = client.post(
            f"/api/v1/audit-requests/{request_body['id']}/runs"
        )
        assert run_response.status_code == 201
        run_body = run_response.json()
        assert run_body["status"] == "COMPLETED"
        assert run_body["verification_status"] == "INCOMPLETE"

        listed = client.get(
            "/api/v1/audit-runs",
            params={"audit_request_id": request_body["id"]},
        )
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        session = app.state.platform_db.session()
        try:
            persisted = session.get(AuditRun, run_body["id"])
            assert persisted is not None
            assert len(persisted.evidence_records) == 1
            assert len(persisted.tasks) == 1
            assert persisted.tasks[0].status == "COMPLETED"
        finally:
            session.close()


def test_unconfigured_runner_fails_without_fabricating_verification() -> None:
    app = create_app("sqlite:///:memory:")
    with TestClient(app) as client:
        client.post("/api/v1/workspaces", json={"id": "w1", "name": "Test"})
        request_body = client.post(
            "/api/v1/audit-requests?workspace_id=w1",
            json=_request_payload(),
        ).json()
        response = client.post(
            f"/api/v1/audit-requests/{request_body['id']}/runs"
        )
        assert response.status_code == 500
        assert response.json() == {"detail": "audit execution failed"}

        session = app.state.platform_db.session()
        try:
            run = session.query(AuditRun).one()
            assert run.status == "FAILED"
            assert run.verification_status is None
            assert run.tasks[0].status == "FAILED"
        finally:
            session.close()


def test_duplicate_identifiers_return_409_and_rollback() -> None:
    app = create_app("sqlite:///:memory:")
    with TestClient(app) as client:
        payload = {"id": "w1", "name": "Original"}
        assert client.post("/api/v1/workspaces", json=payload).status_code == 201
        duplicate = client.post(
            "/api/v1/workspaces",
            json={"id": "w1", "name": "Duplicate"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json() == {"detail": "conflicting identifier"}

        request_payload = _request_payload()
        assert client.post(
            "/api/v1/audit-requests?workspace_id=w1",
            json=request_payload,
        ).status_code == 201
        duplicate_request = client.post(
            "/api/v1/audit-requests?workspace_id=w1",
            json=request_payload,
        )
        assert duplicate_request.status_code == 409
        listed = client.get("/api/v1/audit-requests", params={"workspace_id": "w1"})
        assert len(listed.json()) == 1


def test_missing_workspace_returns_404() -> None:
    with TestClient(create_app("sqlite:///:memory:")) as client:
        response = client.post(
            "/api/v1/audit-requests?workspace_id=missing",
            json=_request_payload("REQ-0002"),
        )
        assert response.status_code == 404


def test_database_connectivity_failure_returns_503() -> None:
    app = create_app(
        "postgresql+psycopg://unavailable@127.0.0.1:1/privacyguard_platform"
        "?connect_timeout=1"
    )
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"detail": "database unavailable"}
