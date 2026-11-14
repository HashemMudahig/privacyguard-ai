"""Request-level audit context builder."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from ..activity.index import ActivityIndex
from ..config import Settings
from ..evidence.coverage import SnapshotAbsenceProof, SnapshotCoverageIndex
from ..evidence.models import ObservedState
from ..evidence.index import EvidenceIndex
from ..evidence.manifest import load_evidence_manifest
from ..evidence.service import build_evidence
from ..identity.index import IdentityIndex
from ..identity.resolver import IdentityResolver
from ..io.bundle import DatasetBundle, load_dataset
from ..linking.linker import ResourceLinker
from ..linking.models import UnresolvedResource
from ..models import DeletionRequest, ResolutionStatus
from ..state.engine import StateEngine
from ..state.models import ResourceKind, ResourceState, StateBasis
from .errors import AuditContextError
from .models import AuditContext

_WORKFLOW_WINDOW = timedelta(hours=2)
_STATE_BEARING_EVENT_TYPES = {
    "DELETE_RECORD",
    "REDACT_RECORD",
    "ANONYMIZE_RECORD",
    "SYNC_RECORD",
    "INDEX_RECORD",
    "RESTORE_BACKUP",
    "UPDATE_RECORD",
    "CREATE_EXPORT",
    "REFRESH_CACHE",
    "SEND_EMAIL",
    "RETAIN_RECORD",
    "DISABLE_DATA_FLOW",
    "BLOCK_RESTORE",
    "CHECK_DATA_FLOW",
    "CHECK_RESTORE_ACCESS",
}

_SNAPSHOT_COLLECTION_BY_CATEGORY = {
    "USER_PROFILE": "customer_profiles",
    "SEARCH_INDEX_ENTRY": "customer_search_documents",
    "ANALYTICS_PROFILE": "customer_analytics_profiles",
    "SUPPORT_MESSAGE": "support_records",
    "SUPPORT_ATTACHMENT": "support_records",
    "USER_EXPORT": "customer_exports",
    "SECURITY_AUDIT_LOG": "security_audit_records",
}


class AuditContextService:
    """Reusable service that builds one audit context per request case."""

    def __init__(self, dataset_dir: str | Path) -> None:
        self.dataset_dir = Path(dataset_dir).expanduser().resolve()
        self.bundle: DatasetBundle = self._load_bundle()
        self.identity_index = IdentityIndex(
            self.bundle.identities, self.bundle.audit_events
        )
        self.resolver = IdentityResolver(self.identity_index)
        evidence_build = build_evidence(self.dataset_dir)
        self.evidence_index = EvidenceIndex(evidence_build.observations)
        manifest = load_evidence_manifest(self.dataset_dir)
        self.snapshot_index = SnapshotCoverageIndex.from_dataset(
            self.dataset_dir, manifest.entries
        )
        self.activity_index = ActivityIndex(self.bundle.system_activity)
        self.linker = ResourceLinker(self.evidence_index, self.activity_index)
        self.state_engine = StateEngine(self.evidence_index, self.activity_index)
        self._requests: dict[str, DeletionRequest] = {}
        for request_file in (self.bundle.sample_requests, self.bundle.eval_requests):
            for row in request_file.rows:
                self._requests.setdefault(row.record.case_id, row.record)
        self._request_source: dict[str, str] = {}
        for label, request_file in (
            ("sample", self.bundle.sample_requests),
            ("eval", self.bundle.eval_requests),
        ):
            for row in request_file.rows:
                self._request_source[row.record.case_id] = label

    def _load_bundle(self) -> DatasetBundle:
        return load_dataset(Settings.from_environment(dataset_dir=self.dataset_dir))

    @classmethod
    def from_settings(cls, settings: Settings) -> "AuditContextService":
        return cls(settings.dataset_dir)

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._requests))

    def request_source(self, case_id: str) -> str | None:
        """Return ``sample`` or ``eval`` for a known case."""
        return self._request_source.get(case_id)

    def build_context(self, case_id: str) -> AuditContext:
        request = self._requests.get(case_id)
        if request is None:
            raise AuditContextError(f"Unknown case_id: {case_id}")
        return self._build_for_request(request)

    def _build_for_request(self, request: DeletionRequest) -> AuditContext:
        resolution = self.resolver.resolve_email(request.email)
        identity = resolution.identity
        if identity is None:
            return AuditContext(
                case_id=request.case_id,
                audit_at=request.audit_at,
                request=request,
                resolution=resolution,
                identity=None,
                uncertainties=(
                    f"Identity could not be resolved: {resolution.status.value}",
                ),
            )

        workflow_start, workflow_end = _workflow_window(request)
        link_result = self.linker.link(
            identity,
            audit_at=request.audit_at,
            workflow_start=workflow_start,
            workflow_end=workflow_end,
        )
        states = self.state_engine.reconstruct(link_result.linked, request.audit_at)
        states, absence_proofs = apply_authoritative_absence(
            states, self.snapshot_index, request.audit_at
        )

        linked_ids = {link.resource_id for link in link_result.linked}
        relevant_observations = self._relevant_observations(
            request, identity, linked_ids
        )
        relevant_activity = self._relevant_activity(
            request, identity, linked_ids
        )
        candidate_events = self._candidate_activity(request, linked_ids)
        unresolved = list(link_result.unresolved)
        candidate_resources = _group_activity_candidates(candidate_events)

        active_flows = tuple(
            state.resource_id for state in states if state.active_data_flow
        )
        restore_risks = tuple(
            state.resource_id for state in states if state.restore_risk
        )
        conflicts = tuple(
            conflict for state in states for conflict in state.conflicts
        )
        uncertainties: list[str] = []
        uncertainties.extend(link_result.warnings)
        for state in states:
            uncertainties.extend(state.uncertainties)
        if resolution.status != ResolutionStatus.RESOLVED:
            uncertainties.append(f"Identity resolution status: {resolution.status.value}")
        if candidate_events:
            uncertainties.append(
                f"{len(candidate_events)} activity event(s) in the reported workflow window "
                "could not be linked to this identity"
            )
        for item in unresolved:
            uncertainties.append(f"Unresolved {item.resource_id or 'resource'}: {item.reason}")

        return AuditContext(
            case_id=request.case_id,
            audit_at=request.audit_at,
            request=request,
            resolution=resolution,
            identity=identity,
            linked_resources=link_result.linked,
            account_candidates=link_result.candidates,
            absence_proofs=absence_proofs,
            unresolved_resources=tuple(unresolved),
            candidate_activity_resources=tuple(candidate_resources),
            states=states,
            active_data_flows=active_flows,
            restore_risks=restore_risks,
            conflicts=conflicts,
            uncertainties=tuple(dict.fromkeys(uncertainties)),
            relevant_observations=relevant_observations,
            relevant_activity=relevant_activity,
        )

    def _relevant_observations(self, request, identity, linked_ids) -> tuple:
        observations = []
        for resource_id in linked_ids:
            observations.extend(
                self.evidence_index.observations_for_resource(
                    resource_id, audit_at=request.audit_at
                )
            )
        observations.extend(
            self.evidence_index.observations_for_identity(
                identity,
                audit_at=request.audit_at,
                include_resource_neighbors=False,
            )
        )
        deduped = {}
        for observation in observations:
            deduped[observation.observation_id] = observation
        return tuple(
            sorted(
                deduped.values(),
                key=lambda item: (
                    item.observed_at or item.captured_at,
                    item.observation_id,
                ),
            )
        )

    def _relevant_activity(self, request, identity, linked_ids) -> tuple:
        events = []
        for resource_id in linked_ids:
            events.extend(
                self.activity_index.events_for_resource(
                    resource_id, audit_at=request.audit_at
                )
            )
        events.extend(
            self.activity_index.events_for_identity(identity, audit_at=request.audit_at)
        )
        events.extend(self._candidate_activity(request, linked_ids))
        deduped = {event.activity_id: event for event in events}
        return tuple(
            sorted(deduped.values(), key=lambda item: (item.event_time, item.activity_id))
        )

    def _candidate_activity(self, request, linked_ids):
        start, end = _workflow_window(request)
        if end < start:
            return ()
        events = self.activity_index.events_in_window(
            start,
            end,
            event_types=_STATE_BEARING_EVENT_TYPES,
        )
        return tuple(event for event in events if event.resource_id not in linked_ids)


def _workflow_window(request):
    """Return the candidate activity window, never before the request itself."""
    start = max(request.requested_at, request.reported_at - _WORKFLOW_WINDOW)
    end = min(request.audit_at, request.reported_at + _WORKFLOW_WINDOW)
    return start, end


def _group_activity_candidates(events) -> list[UnresolvedResource]:
    grouped: dict[str, list] = {}
    for event in events:
        grouped.setdefault(event.resource_id, []).append(event)
    unresolved: list[UnresolvedResource] = []
    for resource_id, resource_events in sorted(grouped.items()):
        unresolved.append(
            UnresolvedResource(
                resource_id=resource_id,
                system_id=resource_events[0].target_system,
                reason=(
                    "Activity in the reported workflow window is not linked to the "
                    "identity by an explicit identifier or reference"
                ),
                activity_ids=tuple(event.activity_id for event in resource_events),
                confidence=0.0,
            )
        )
    return unresolved


def apply_authoritative_absence(
    states: tuple[ResourceState, ...],
    snapshot_index: SnapshotCoverageIndex,
    audit_at,
) -> tuple[tuple[ResourceState, ...], tuple[SnapshotAbsenceProof, ...]]:
    """Upgrade an unverified record state only with complete-snapshot proof.

    Nonappearance in a partial snapshot is not evidence. Confirmed direct
    observations are already handled by ``StateEngine`` and are not replaced.
    """
    resolved: list[ResourceState] = []
    proofs: list[SnapshotAbsenceProof] = []
    for state in states:
        if state.verified or state.kind != ResourceKind.RECORD:
            resolved.append(state)
            continue
        categories = [category.upper() for category in state.data_categories]
        collections = [
            _SNAPSHOT_COLLECTION_BY_CATEGORY[category]
            for category in categories
            if category in _SNAPSHOT_COLLECTION_BY_CATEGORY
        ]
        if not collections:
            resolved.append(state)
            continue
        result = snapshot_index.prove_absence(
            state.resource_id,
            system_id=state.system_ids[0] if state.system_ids else None,
            collection=collections[0],
            audit_at=audit_at,
        )
        proof = result.proof
        if proof is None:
            resolved.append(state)
            continue
        proofs.append(proof)
        basis = StateBasis(
            source_type="EVIDENCE",
            source_id=proof.file_id,
            timestamp=proof.captured_at,
            state=ObservedState.ABSENT,
            detail=proof.reason,
            location=proof.provenance,
            confidence=proof.confidence,
        )
        resolved.append(
            state.model_copy(
                update={
                    "state": ObservedState.ABSENT,
                    "confidence": proof.confidence,
                    "verified": True,
                    "basis": (*state.basis, basis),
                    "evidence_ids": (*state.evidence_ids, proof.file_id),
                    "uncertainties": tuple(
                        item
                        for item in state.uncertainties
                        if "Missing evidence" not in item
                    ),
                    "latest_evidence_at": proof.captured_at,
                }
            )
        )
    return tuple(resolved), tuple(proofs)


def build_audit_context(
    case_id: str,
    *,
    dataset_dir: str | Path | None = None,
) -> AuditContext:
    """Convenience function that builds a context with a fresh service."""
    if dataset_dir is None:
        settings = Settings.from_environment()
        service = AuditContextService.from_settings(settings)
    else:
        service = AuditContextService(dataset_dir)
    return service.build_context(case_id)
