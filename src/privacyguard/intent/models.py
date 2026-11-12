"""Request intent models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class IntentStatus(StrEnum):
    DELETION_AUTHORIZED = "DELETION_AUTHORIZED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNCERTAIN = "UNCERTAIN"


class RequestIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    status: IntentStatus
    authorizes_deletion: bool
    confidence: float = Field(ge=0.0, le=1.0)
    method: str
    matched_terms: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
