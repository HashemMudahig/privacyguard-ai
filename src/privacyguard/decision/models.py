"""Final audit decision models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ..intent.models import RequestIntent
from ..planning.models import AuditStep
from ..policy.models import PolicyEvaluation


class DeletionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AuditResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    deletion_status: DeletionStatus
    steps: tuple[AuditStep, ...] = ()
    intent: RequestIntent
    policy: PolicyEvaluation
    coverage_gaps: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    status_reasons: tuple[str, ...] = ()
    provisional: bool = False
