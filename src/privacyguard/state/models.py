"""Models for temporal resource state reconstruction."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..evidence.models import ObservedState


class ResourceKind(StrEnum):
    RECORD = "RECORD"
    FLOW = "FLOW"
    BACKUP = "BACKUP"
    UNKNOWN = "UNKNOWN"


class RecreationStatus(StrEnum):
    NONE = "NONE"
    SUSPECTED = "SUSPECTED"
    CONFIRMED = "CONFIRMED"


class StateBasis(BaseModel):
    """One source record used in a state decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: Literal["EVIDENCE", "ACTIVITY"]
    source_id: str
    timestamp: datetime
    state: ObservedState
    detail: str
    location: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class StateConflict(BaseModel):
    """A disagreement between observations, claims or copies."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_id: str
    description: str
    competing_states: tuple[ObservedState, ...]
    source_ids: tuple[str, ...]
    resolution: ObservedState
    rule: str


class ResourceState(BaseModel):
    """Best-supported state for one linked resource at an audit timestamp."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_id: str
    kind: ResourceKind
    system_ids: tuple[str, ...] = ()
    data_categories: tuple[str, ...] = ()
    state: ObservedState
    confidence: float = Field(ge=0.0, le=1.0)
    verified: bool
    basis: tuple[StateBasis, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    activity_ids: tuple[str, ...] = ()
    conflicts: tuple[StateConflict, ...] = ()
    uncertainties: tuple[str, ...] = ()
    recreated: bool = False
    recreation_status: RecreationStatus = RecreationStatus.NONE
    active_data_flow: bool = False
    restore_risk: bool = False
    latest_evidence_at: datetime | None = None
    latest_activity_at: datetime | None = None
