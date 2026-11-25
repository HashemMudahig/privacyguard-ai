from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from .models import AuditRun
from .repository import AuditRequestRepository, AuditRunRepository, AuditTaskRepository, EvidenceRepository


@dataclass(frozen=True)
class AuditOutcome:
    status: str
    step_count: int
    evidence_ids: tuple[str, ...] = ()
    summary: Optional[str] = None


class AuditRunner(Protocol):
    def run(self, audit_request) -> AuditOutcome: ...


class AuditExecutionService:
    def __init__(self, session_factory, runner: AuditRunner):
        self.session_factory = session_factory
        self.runner = runner

    def trigger(self, audit_request_id: str) -> AuditRun:
        session = self.session_factory()
        try:
            request = AuditRequestRepository(session).get(audit_request_id)
            if request is None:
                raise LookupError("audit request not found")

            existing = (
                session.query(AuditRun)
                .filter(
                    AuditRun.audit_request_id == request.id,
                    AuditRun.status.in_(("PENDING", "RUNNING")),
                )
                .order_by(AuditRun.created_at.desc())
                .first()
            )
            if existing is not None:
                return existing

            run = AuditRunRepository(session).create(request.id)
            task = AuditTaskRepository(session).create(run.id, "audit_execution")
            # Persist durable technical PENDING state before invoking an external
            # audit runner. Completion/failure is a separate transaction.
            session.commit()

            try:
                outcome = self.runner.run(request)
            except Exception:
                AuditTaskRepository(session).update_status(task, "FAILED")
                AuditRunRepository(session).complete(run, "FAILED", 0)
                session.commit()
                raise

            for eid in outcome.evidence_ids:
                EvidenceRepository(session).add(run.id, eid)
            AuditTaskRepository(session).update_status(task, "COMPLETED")
            completed = AuditRunRepository(session).complete(
                run, "COMPLETED", outcome.step_count, verification_status=outcome.status
            )
            session.commit()
            return completed
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
