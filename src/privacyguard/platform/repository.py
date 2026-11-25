from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from .models import AuditRequest, AuditRun, AuditTask, EvidenceRecord, Workspace


class WorkspaceRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, workspace_id: str, name: str) -> Workspace:
        workspace = Workspace(
            id=workspace_id,
            name=name,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(workspace)
        self.session.flush()
        return workspace

    def get(self, workspace_id: str) -> Workspace | None:
        return self.session.get(Workspace, workspace_id)


class AuditRequestRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, workspace_id: str, payload: Any) -> AuditRequest:
        request = AuditRequest(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            request_id=payload.request_id,
            email=payload.email,
            audit_at=payload.audit_at,
            request_text=payload.request_text,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(request)
        self.session.flush()
        return request

    def list(self, workspace_id: str, limit: int = 50, offset: int = 0) -> list[AuditRequest]:
        return (
            self.session.query(AuditRequest)
            .filter(AuditRequest.workspace_id == workspace_id)
            .order_by(AuditRequest.created_at)
            .offset(offset)
            .limit(limit)
            .all()
        )

    def get(self, request_id: str) -> AuditRequest | None:
        return self.session.get(AuditRequest, request_id)


class AuditRunRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, audit_request_id: str) -> AuditRun:
        run = AuditRun(
            id=str(uuid.uuid4()),
            audit_request_id=audit_request_id,
            status="PENDING",
            step_count=0,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def get(self, run_id: str) -> AuditRun | None:
        return self.session.get(AuditRun, run_id)

    def list_for_request(self, audit_request_id: str) -> list[AuditRun]:
        return (
            self.session.query(AuditRun)
            .filter(AuditRun.audit_request_id == audit_request_id)
            .order_by(AuditRun.created_at)
            .all()
        )

    def complete(
        self,
        run: AuditRun,
        status: str,
        step_count: int,
        verification_status: str | None = None,
    ) -> AuditRun:
        run.status = status
        run.step_count = step_count
        run.verification_status = verification_status
        run.completed_at = datetime.now(timezone.utc)
        self.session.flush()
        return run


class EvidenceRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(
        self,
        run_id: str,
        evidence_id: str,
        source: str = "audit_runner",
        resource_id: str | None = None,
        observed_state: str = "UNKNOWN",
    ) -> EvidenceRecord:
        record = EvidenceRecord(
            id=f"{run_id}:{evidence_id}",
            audit_run_id=run_id,
            source=source,
            resource_id=resource_id or evidence_id,
            observed_state=observed_state,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def list_for_run(self, run_id: str) -> list[EvidenceRecord]:
        return (
            self.session.query(EvidenceRecord)
            .filter(EvidenceRecord.audit_run_id == run_id)
            .all()
        )


class AuditTaskRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, run_id: str, task_type: str) -> AuditTask:
        task = AuditTask(
            id=str(uuid.uuid4()),
            audit_run_id=run_id,
            task_type=task_type,
            status="PENDING",
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(task)
        self.session.flush()
        return task

    def update_status(self, task: AuditTask, status: str) -> AuditTask:
        task.status = status
        self.session.flush()
        return task
