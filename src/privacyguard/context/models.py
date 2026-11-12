"""Request-level audit context models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from ..activity.models import SystemActivity
from ..evidence.models import EvidenceObservation
from ..linking.models import LinkedResource, UnresolvedResource
from ..models import DeletionRequest, IdentityResolution, ResolvedIdentity
from ..state.models import ResourceState, StateConflict


class AuditContext(BaseModel):
    """Structured, provenance-rich context for one deletion request.

    This model intentionally stops before policy classification and remediation.
    It is the input contract for Sprint 2C.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    audit_at: datetime
    request: DeletionRequest
    resolution: IdentityResolution
    identity: ResolvedIdentity | None
    linked_resources: tuple[LinkedResource, ...] = ()
    unresolved_resources: tuple[UnresolvedResource, ...] = ()
    candidate_activity_resources: tuple[UnresolvedResource, ...] = ()
    states: tuple[ResourceState, ...] = ()
    active_data_flows: tuple[str, ...] = ()
    restore_risks: tuple[str, ...] = ()
    conflicts: tuple[StateConflict, ...] = ()
    uncertainties: tuple[str, ...] = ()
    relevant_observations: tuple[EvidenceObservation, ...] = ()
    relevant_activity: tuple[SystemActivity, ...] = ()
