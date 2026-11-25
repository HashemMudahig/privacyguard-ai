from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import PlatformDatabase, init_test_schema, resolve_database_url
from .repository import AuditRequestRepository, AuditRunRepository, WorkspaceRepository
from .schemas import (
    AuditRequestCreate,
    AuditRequestRead,
    AuditRunRead,
    WorkspaceCreate,
    WorkspaceRead,
)
class _UnconfiguredRunner:
    def run(self, audit_request):
        raise RuntimeError("audit runner is not configured")


def create_app(
    database_url: str | None = None,
    audit_runner=None,
    *,
    create_test_schema: bool | None = None,
) -> FastAPI:
    resolved_url = resolve_database_url(database_url)
    platform_db = PlatformDatabase(resolved_url)

    parsed_url = make_url(resolved_url)
    is_memory_sqlite = (
        parsed_url.get_backend_name() == "sqlite"
        and parsed_url.database in {None, "", ":memory:"}
    )
    if create_test_schema is None:
        create_test_schema = is_memory_sqlite
    if create_test_schema:
        init_test_schema(platform_db.engine)

    from .service import AuditExecutionService

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            platform_db.dispose()

    app = FastAPI(
        title="PrivacyGuard AI Platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.platform_db = platform_db
    app.state.audit_service = AuditExecutionService(
        platform_db.session_factory,
        audit_runner if audit_runner is not None else _UnconfiguredRunner(),
    )

    def get_session() -> Session:
        session = platform_db.session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(
        _request: Request,
        _exc: IntegrityError,
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "conflicting identifier"})

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready() -> dict[str, str]:
        try:
            with platform_db.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            raise HTTPException(status_code=503, detail="database unavailable")
        return {"status": "ready"}

    @app.post("/api/v1/workspaces", response_model=WorkspaceRead, status_code=201)
    def create_workspace(payload: WorkspaceCreate, session: Session = Depends(get_session)) -> WorkspaceRead:
        return WorkspaceRepository(session).create(payload.id, payload.name)

    @app.get("/api/v1/audit-requests", response_model=list[AuditRequestRead])
    def list_requests(workspace_id: str = Query(...), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), session: Session = Depends(get_session)) -> list[AuditRequestRead]:
        rows = AuditRequestRepository(session).list(workspace_id, limit, offset)
        return [AuditRequestRead.model_validate(row) for row in rows]

    @app.post("/api/v1/audit-requests", response_model=AuditRequestRead, status_code=201)
    def create_request(workspace_id: str = Query(...), payload: AuditRequestCreate = None, session: Session = Depends(get_session)) -> AuditRequestRead:
        if WorkspaceRepository(session).get(workspace_id) is None:
            raise HTTPException(status_code=404, detail="workspace not found")
        return AuditRequestRepository(session).create(workspace_id, payload)

    @app.get("/api/v1/audit-requests/{request_id}", response_model=AuditRequestRead)
    def get_request(request_id: str, session: Session = Depends(get_session)) -> AuditRequestRead:
        row = AuditRequestRepository(session).get(request_id)
        if row is None:
            raise HTTPException(status_code=404, detail="audit request not found")
        return row

    @app.post("/api/v1/audit-requests/{request_id}/runs", response_model=AuditRunRead, status_code=201)
    def trigger_run(request_id: str, session: Session = Depends(get_session)) -> AuditRunRead:
        row = AuditRequestRepository(session).get(request_id)
        if row is None:
            raise HTTPException(status_code=404, detail="audit request not found")
        service = app.state.audit_service
        try:
            run = service.trigger(row.id)
        except LookupError:
            raise HTTPException(status_code=404, detail="audit request not found")
        except Exception:
            raise HTTPException(status_code=500, detail="audit execution failed")
        refreshed = AuditRunRepository(session).get(run.id)
        return refreshed if refreshed is not None else run

    @app.get("/api/v1/audit-runs", response_model=list[AuditRunRead])
    def list_runs(audit_request_id: str = Query(...), session: Session = Depends(get_session)) -> list[AuditRunRead]:
        rows = AuditRunRepository(session).list_for_request(audit_request_id)
        return [AuditRunRead.model_validate(row) for row in rows]

    @app.get("/api/v1/audit-runs/{run_id}", response_model=AuditRunRead)
    def get_run(run_id: str, session: Session = Depends(get_session)) -> AuditRunRead:
        row = AuditRunRepository(session).get(run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="audit run not found")
        return row

    return app
