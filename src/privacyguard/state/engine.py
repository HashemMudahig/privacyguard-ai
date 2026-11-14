"""Deterministic temporal resource state reconstruction.

Evidence observations are authoritative when they explicitly describe a state.
Activity rows are operational claims and only become the provisional state when
no evidence observation is available. Missing observations are never treated as
proof of absence without snapshot scope.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from ..activity.index import ActivityIndex
from ..activity.models import ReportedResult, SystemActivity
from ..evidence.index import EvidenceIndex
from ..evidence.models import EvidenceFormat, EvidenceObservation, ObservedState, coerce_timestamp
from ..linking.models import LinkedResource
from .models import (
    RecreationStatus,
    ResourceKind,
    ResourceState,
    StateBasis,
    StateConflict,
)

_RECORD_PRECEDENCE = {
    ObservedState.PRESENT: 4,
    ObservedState.REDACTED: 3,
    ObservedState.ANONYMIZED: 2,
    ObservedState.ABSENT: 1,
    ObservedState.UNKNOWN: 0,
}
_FLOW_PRECEDENCE = {
    ObservedState.ACTIVE: 3,
    ObservedState.DISABLED: 2,
    ObservedState.BLOCKED: 1,
    ObservedState.UNKNOWN: 0,
}
_BACKUP_PRECEDENCE = {
    ObservedState.ACTIVE: 3,
    ObservedState.BLOCKED: 2,
    ObservedState.DISABLED: 1,
    ObservedState.UNKNOWN: 0,
}

_ANALYTICS_CATEGORIES = {
    "ANALYTICS_PROFILE",
    "PRODUCT_TELEMETRY",
    "customer_analytics_profiles",
    "customer_analytics_reports",
    "profiles",
    "analytics_profiles",
    "analytics_identity_store",
}
_TOMBSTONE_CATEGORIES = {
    "ACCOUNT_TOMBSTONE",
    "deleted_customer_references",
}
_SUPPORT_MESSAGE_CATEGORIES = {
    "SUPPORT_MESSAGE",
    "support_conversations",
    "support_records",
    "tickets",
}
_RECREATION_EVENT_TYPES = {
    "SYNC_RECORD",
    "INDEX_RECORD",
    "RESTORE_BACKUP",
    "UPDATE_RECORD",
    "CREATE_EXPORT",
    "REFRESH_CACHE",
    "SEND_EMAIL",
}


@dataclass(frozen=True, slots=True)
class _EffectiveState:
    state: ObservedState
    rule: str
    confidence: float
    inferred: bool


class StateEngine:
    """Reconstruct resource states at ``audit_at`` from evidence and activity."""

    def __init__(self, evidence_index: EvidenceIndex, activity_index: ActivityIndex) -> None:
        self.evidence_index = evidence_index
        self.activity_index = activity_index

    def reconstruct(
        self,
        linked_resources: Iterable[LinkedResource],
        audit_at: datetime | str,
    ) -> tuple[ResourceState, ...]:
        cutoff = coerce_timestamp(audit_at)
        if cutoff is None:
            raise ValueError("audit_at is required for state reconstruction")
        return tuple(
            self._reconstruct_one(link, cutoff)
            for link in sorted(linked_resources, key=lambda item: item.resource_id)
        )

    def _reconstruct_one(self, link: LinkedResource, audit_at: datetime) -> ResourceState:
        kind = _resource_kind(link)
        observations = self.evidence_index.observations_for_resource(
            link.resource_id, audit_at=audit_at
        )
        all_observations = self.evidence_index.observations_for_resource(
            link.resource_id
        )
        events = self.activity_index.events_for_resource(
            link.resource_id, audit_at=audit_at
        )

        conflicts: list[StateConflict] = []
        uncertainties: list[str] = list(link.warnings)
        basis: list[StateBasis] = []
        evidence_ids: list[str] = []
        activity_ids: list[str] = []

        effective = [
            (observation, _effective_observation_state(observation))
            for observation in observations
        ]
        evidence_latest, evidence_state, evidence_conf, evidence_verified = _aggregate_evidence(
            link, kind, effective, conflicts, uncertainties
        )
        for observation, decision in evidence_latest:
            basis.append(_evidence_basis(observation, decision))
            if observation.observation_id not in evidence_ids:
                evidence_ids.append(observation.observation_id)

        claims = [
            (event, claim)
            for event in events
            if (claim := _activity_claim(event)) is not None
        ]
        latest_claim: tuple[SystemActivity, _EffectiveState] | None = None
        claim_basis: list[StateBasis] = []
        for event, claim in claims:
            claim_basis.append(_activity_basis(event, claim))
            if event.activity_id not in activity_ids:
                activity_ids.append(event.activity_id)
            if latest_claim is None or (event.event_time, event.activity_id) > (
                latest_claim[0].event_time,
                latest_claim[0].activity_id,
            ):
                latest_claim = (event, claim)

        if (
            evidence_state == ObservedState.PRESENT
            and latest_claim is not None
            and latest_claim[1].state in {ObservedState.REDACTED, ObservedState.ANONYMIZED}
        ):
            has_direct = any(
                observation.emails
                or observation.phones
                or observation.email_hashes
                for observation, _ in evidence_latest
            )
            has_any = any(
                observation.user_ids
                or observation.emails
                or observation.phones
                or observation.email_hashes
                for observation, _ in evidence_latest
            )
            target = latest_claim[1].state
            allowed = (
                target == ObservedState.REDACTED and not has_direct
            ) or (
                target == ObservedState.ANONYMIZED and not has_any
            )
            if allowed:
                evidence_state = target
                evidence_conf = latest_claim[1].confidence
                direct_redaction_confirmation = (
                    target == ObservedState.REDACTED
                    and any(
                        _has_explicit_null_support_pii_fields(observation)
                        for observation, _ in evidence_latest
                    )
                )
                evidence_verified = direct_redaction_confirmation
                if not direct_redaction_confirmation:
                    uncertainties.append(
                        "State is based on successful REDACT/ANONYMIZE activity; "
                        "evidence contains no direct identifiers"
                    )

        if evidence_state is not None:
            state = evidence_state
            confidence = evidence_conf
            verified = evidence_verified
            if latest_claim is not None and latest_claim[1].state != state:
                conflicts.append(
                    StateConflict(
                        resource_id=link.resource_id,
                        description="Activity claim differs from evidence-backed state",
                        competing_states=(latest_claim[1].state, state),
                        source_ids=(latest_claim[0].activity_id, *evidence_ids),
                        resolution=state,
                        rule="Evidence observations override reported activity claims",
                    )
                )
                confidence = max(0.5, confidence - 0.05)
            if latest_claim is not None:
                basis.append(_activity_basis(latest_claim[0], latest_claim[1]))
        elif latest_claim is not None:
            state = latest_claim[1].state
            confidence = latest_claim[1].confidence
            verified = False
            uncertainties.append(
                "No independent evidence observation; state is based on reported activity only"
            )
            basis.append(_activity_basis(latest_claim[0], latest_claim[1]))
        else:
            state = ObservedState.UNKNOWN
            confidence = 0.0
            verified = False
            uncertainties.append("No evidence observation or state-bearing activity at or before audit_at")

        if evidence_state is None and observations:
            unknowns = sum(
                1
                for _, decision in effective
                if decision.state == ObservedState.UNKNOWN
            )
            if unknowns:
                uncertainties.append(
                    f"{unknowns} evidence observation(s) at or before audit_at did not expose a state"
                )

        if not observations:
            uncertainties.append("No evidence observations at or before audit_at")

        post_audit = [
            observation
            for observation in all_observations
            if observation.captured_at > audit_at
        ]
        if post_audit:
            uncertainties.append(
                f"{len(post_audit)} evidence observation(s) captured after audit_at were excluded"
            )

        recreation_status, recreation_conflicts, recreation_basis = _detect_recreation(
            link, observations, events, audit_at
        )
        conflicts.extend(recreation_conflicts)
        for item, event_or_observation in recreation_basis:
            basis.append(item)
            if isinstance(event_or_observation, SystemActivity):
                if event_or_observation.activity_id not in activity_ids:
                    activity_ids.append(event_or_observation.activity_id)
            else:
                if event_or_observation.observation_id not in evidence_ids:
                    evidence_ids.append(event_or_observation.observation_id)

        if _tombstone_exposed(link, state, observations):
            conflicts.append(
                StateConflict(
                    resource_id=link.resource_id,
                    description="Tombstone still contains direct identifiers",
                    competing_states=(ObservedState.PRESENT, ObservedState.REDACTED),
                    source_ids=tuple(evidence_ids),
                    resolution=ObservedState.PRESENT,
                    rule="Direct identifiers are present in a tombstone record",
                )
            )
            uncertainties.append("Tombstone contains direct identifiers")

        latest_claim_active = (
            latest_claim is not None and latest_claim[1].state == ObservedState.ACTIVE
        )
        active_flow = False
        restore_risk = False
        if kind == ResourceKind.FLOW:
            active_flow = state == ObservedState.ACTIVE or (
                evidence_state is None and latest_claim_active
            )
        if kind == ResourceKind.BACKUP:
            restore_risk = (
                state == ObservedState.ACTIVE
                or (evidence_state is None and latest_claim_active)
                or any(_restore_allowed(observation) for observation, _ in evidence_latest)
            )

        latest_evidence_at = max(
            (
                observation.observed_at or observation.captured_at
                for observation in observations
            ),
            default=None,
        )
        latest_activity_at = max((event.event_time for event in events), default=None)

        return ResourceState(
            resource_id=link.resource_id,
            kind=kind,
            system_ids=tuple(
                sorted(
                    {
                        *(link.system_ids),
                        *(observation.system_id for observation in observations if observation.system_id),
                    }
                )
            ),
            data_categories=tuple(
                sorted(
                    {
                        *(link.data_categories),
                        *(observation.data_category for observation in observations if observation.data_category),
                    }
                )
            ),
            state=state,
            confidence=round(max(0.0, min(1.0, confidence)), 3),
            verified=verified,
            basis=tuple(_dedupe_basis(basis)),
            evidence_ids=tuple(dict.fromkeys(evidence_ids)),
            activity_ids=tuple(dict.fromkeys(activity_ids)),
            conflicts=tuple(conflicts),
            uncertainties=tuple(dict.fromkeys(uncertainties)),
            recreated=recreation_status != RecreationStatus.NONE,
            recreation_status=recreation_status,
            active_data_flow=active_flow,
            restore_risk=restore_risk,
            latest_evidence_at=latest_evidence_at,
            latest_activity_at=latest_activity_at,
        )


def _resource_kind(link: LinkedResource) -> ResourceKind:
    resource_id = link.resource_id
    categories = {category.upper() for category in link.data_categories}
    if resource_id.startswith("data_flow_") or "DATA_FLOW" in categories:
        return ResourceKind.FLOW
    if resource_id.startswith("backup_") or "BACKUP_ARCHIVE" in categories:
        return ResourceKind.BACKUP
    if resource_id:
        return ResourceKind.RECORD
    return ResourceKind.UNKNOWN


def _effective_observation_state(observation: EvidenceObservation) -> _EffectiveState:
    state = observation.observed_state
    has_direct_identifiers = bool(
        observation.emails or observation.phones or observation.email_hashes
    )
    has_any_identifiers = bool(observation.user_ids or has_direct_identifiers)
    tombstone = _is_tombstone(observation)
    analytics = _is_analytics(observation)
    method = (observation.format == EvidenceFormat.PNG) or (observation.provenance.extraction_method or "").lower().startswith("windows_ocr")
    confidence = min(0.95, observation.confidence)

    if _is_support_message(observation) and _has_explicit_redaction_marker(observation):
        return _EffectiveState(
            ObservedState.REDACTED,
            "support record contains an explicit redaction marker",
            confidence,
            False,
        )

    if tombstone and not has_direct_identifiers:
        if state in {ObservedState.UNKNOWN, ObservedState.PRESENT}:
            explicit_nulls = _has_explicit_null_identifier_fields(observation)
            return _EffectiveState(
                ObservedState.REDACTED,
                (
                    "tombstone explicitly stores null direct-identifier fields"
                    if explicit_nulls
                    else "tombstone structure with no direct identifiers"
                ),
                min(0.9, confidence),
                not explicit_nulls,
            )
    if analytics and not has_any_identifiers:
        if state in {ObservedState.UNKNOWN, ObservedState.PRESENT}:
            return _EffectiveState(
                ObservedState.ANONYMIZED,
                "analytics record with no attributable identifiers",
                min(0.85, confidence),
                True,
            )
    if state == ObservedState.UNKNOWN and _record_presence_evidence(
        observation, has_direct_identifiers
    ):
        return _EffectiveState(
            ObservedState.PRESENT,
            "direct identifiers present in a completed record observation",
            0.85,
            False,
        )
    if state == ObservedState.UNKNOWN:
        return _EffectiveState(
            ObservedState.UNKNOWN,
            "no explicit state field",
            0.0,
            False,
        )
    return _EffectiveState(
        state,
        observation.state_field or "explicit evidence state",
        confidence,
        method,
    )


def _has_explicit_redaction_marker(observation: EvidenceObservation) -> bool:
    """Return true only for a literal marker carried by the evidence record."""
    marker_fields = ("message_text", "message", "body", "content", "text")
    markers = {"[redacted]", "<redacted>", "redacted"}
    for field in marker_fields:
        value = observation.attributes.get(field)
        if isinstance(value, str) and value.strip().lower() in markers:
            return True
    return False


def _has_explicit_null_identifier_fields(observation: EvidenceObservation) -> bool:
    """Require schema-visible nulls; an omitted field is not absence proof."""
    direct_fields = ("name", "email", "phone")
    attributes = observation.attributes
    return all(field in attributes for field in direct_fields) and all(
        attributes.get(field) in {None, "", "[REDACTED]"}
        for field in direct_fields
    )


def _has_explicit_null_support_pii_fields(observation: EvidenceObservation) -> bool:
    """Recognize a support schema that directly exposes all requester PII fields."""
    if not _is_support_message(observation):
        return False
    fields = ("requester_name", "requester_email", "requester_phone")
    attributes = observation.attributes
    return all(field in attributes for field in fields) and all(
        attributes.get(field) in {None, "", "[REDACTED]"}
        for field in fields
    )


def _record_presence_evidence(
    observation: EvidenceObservation, has_direct_identifiers: bool
) -> bool:
    if not observation.resource_id or not has_direct_identifiers:
        return False
    event = str(observation.attributes.get("event") or "").lower()
    if event and "started" in event:
        return False
    if observation.format.value in {"json", "sql", "txt"}:
        return True
    if not event:
        return False
    return any(token in event for token in ("completed", "read", "scan", "pii"))


def _aggregate_evidence(
    link: LinkedResource,
    kind: ResourceKind,
    effective: list[tuple[EvidenceObservation, _EffectiveState]],
    conflicts: list[StateConflict],
    uncertainties: list[str],
) -> tuple[
    list[tuple[EvidenceObservation, _EffectiveState]],
    ObservedState | None,
    float,
    bool,
]:
    grouped: dict[tuple[str, str, str], list[tuple[EvidenceObservation, _EffectiveState]]] = defaultdict(list)
    for observation, decision in effective:
        key = (
            observation.system_id or "UNKNOWN",
            observation.data_category or "UNKNOWN",
            str(observation.attributes.get("_table") or "default"),
        )
        grouped[key].append((observation, decision))

    selected: list[tuple[EvidenceObservation, _EffectiveState]] = []
    for group in grouped.values():
        known = [
            (observation, decision)
            for observation, decision in group
            if decision.state != ObservedState.UNKNOWN
        ]
        candidates = known or group
        selected.append(
            max(
                candidates,
                key=lambda item: (
                    item[0].observed_at or item[0].captured_at,
                    item[0].observation_id,
                ),
            )
        )

    known_selected = [
        (observation, decision)
        for observation, decision in selected
        if decision.state != ObservedState.UNKNOWN
    ]
    if not known_selected:
        return selected, None, 0.0, False

    states = {decision.state for _, decision in known_selected}
    precedence = _precedence_for(kind)
    resolution = max(states, key=lambda state: precedence.get(state, 0))
    if len(states) > 1:
        conflicts.append(
            StateConflict(
                resource_id=link.resource_id,
                description="Multiple evidence sources disagree on resource state",
                competing_states=tuple(sorted(states, key=lambda state: state.value)),
                source_ids=tuple(
                    observation.observation_id for observation, _ in known_selected
                ),
                resolution=resolution,
                rule=f"Conservative {kind.value} precedence across independent sources",
            )
        )
        if _primary_replica_drift(known_selected):
            conflicts.append(
                StateConflict(
                    resource_id=link.resource_id,
                    description="Primary and replica evidence disagree",
                    competing_states=tuple(sorted(states, key=lambda state: state.value)),
                    source_ids=tuple(
                        observation.observation_id for observation, _ in known_selected
                    ),
                    resolution=resolution,
                    rule="A copy that remains PRESENT is treated as a remaining copy",
                )
            )

    confidence = max(decision.confidence for _, decision in known_selected)
    if len(states) > 1:
        confidence = max(0.5, confidence - 0.05 * (len(states) - 1))
    verified = any(not decision.inferred for _, decision in known_selected)
    if not verified:
        uncertainties.append(
            "State is inferred or extracted with low confidence, not a fully verified state field"
        )
    return known_selected, resolution, confidence, verified


def _precedence_for(kind: ResourceKind) -> dict[ObservedState, int]:
    if kind == ResourceKind.FLOW:
        return _FLOW_PRECEDENCE
    if kind == ResourceKind.BACKUP:
        return _BACKUP_PRECEDENCE
    return _RECORD_PRECEDENCE


def _primary_replica_drift(
    selected: list[tuple[EvidenceObservation, _EffectiveState]],
) -> bool:
    has_primary = False
    has_replica = False
    for observation, _ in selected:
        table = str(observation.attributes.get("_table") or "").lower()
        if "primary" in table:
            has_primary = True
        if "replica" in table:
            has_replica = True
    return has_primary and has_replica


def _is_tombstone(observation: EvidenceObservation) -> bool:
    if observation.resource_id and observation.resource_id.startswith("tombstone_"):
        return True
    category = (observation.data_category or "").upper()
    if category in _TOMBSTONE_CATEGORIES:
        return True
    return str(observation.attributes.get("account_status") or "").upper() == "DELETED"


def _is_analytics(observation: EvidenceObservation) -> bool:
    category = observation.data_category or ""
    if category in _ANALYTICS_CATEGORIES:
        return True
    return "analytics" in category.lower()


def _is_support_message(observation: EvidenceObservation) -> bool:
    return (observation.data_category or "") in _SUPPORT_MESSAGE_CATEGORIES


def _tombstone_exposed(
    link: LinkedResource,
    state: ObservedState,
    observations: tuple[EvidenceObservation, ...],
) -> bool:
    if state != ObservedState.PRESENT:
        return False
    if not any(_is_tombstone(observation) for observation in observations):
        return False
    return any(
        observation.emails or observation.phones or observation.email_hashes
        for observation in observations
    )


def _restore_allowed(observation: EvidenceObservation) -> bool:
    value = observation.attributes.get("restore_allowed")
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    return str(value).strip().lower() in {"1", "true", "yes"}


def _activity_claim(event: SystemActivity) -> _EffectiveState | None:
    success = event.reported_result == ReportedResult.SUCCESS
    partial = event.reported_result == ReportedResult.PARTIAL

    if event.metadata.state_claim is not None and success:
        return _EffectiveState(
            event.metadata.state_claim,
            event.metadata.state_claim_source or "activity details state",
            0.55,
            False,
        )

    event_type = event.event_type
    if event_type == "DELETE_RECORD":
        if success:
            return _EffectiveState(ObservedState.ABSENT, "DELETE_RECORD SUCCESS claim", 0.6, False)
        return _EffectiveState(ObservedState.PRESENT, f"DELETE_RECORD {event.reported_result.value} claim", 0.45, False)
    if event_type == "REDACT_RECORD":
        if success:
            return _EffectiveState(ObservedState.REDACTED, "REDACT_RECORD SUCCESS claim", 0.6, False)
        return _EffectiveState(ObservedState.PRESENT, f"REDACT_RECORD {event.reported_result.value} claim", 0.45, False)
    if event_type == "ANONYMIZE_RECORD":
        if success:
            return _EffectiveState(ObservedState.ANONYMIZED, "ANONYMIZE_RECORD SUCCESS claim", 0.6, False)
        return _EffectiveState(ObservedState.PRESENT, f"ANONYMIZE_RECORD {event.reported_result.value} claim", 0.45, False)
    if event_type in {"SYNC_RECORD", "INDEX_RECORD", "REFRESH_CACHE", "CREATE_EXPORT", "SEND_EMAIL", "RETAIN_RECORD", "UPDATE_RECORD", "RESTORE_BACKUP"}:
        if success or partial:
            confidence = 0.55 if success else 0.4
            return _EffectiveState(
                ObservedState.PRESENT,
                f"{event_type} {event.reported_result.value} claim",
                confidence,
                False,
            )
        return None
    if event_type == "DISABLE_DATA_FLOW":
        if success:
            return _EffectiveState(ObservedState.DISABLED, "DISABLE_DATA_FLOW SUCCESS claim", 0.6, False)
        return _EffectiveState(ObservedState.ACTIVE, f"DISABLE_DATA_FLOW {event.reported_result.value} claim", 0.45, False)
    if event_type == "BLOCK_RESTORE":
        if success:
            return _EffectiveState(ObservedState.BLOCKED, "BLOCK_RESTORE SUCCESS claim", 0.6, False)
        return _EffectiveState(ObservedState.ACTIVE, f"BLOCK_RESTORE {event.reported_result.value} claim", 0.45, False)
    if event_type in {"CHECK_DATA_FLOW", "CHECK_RESTORE_ACCESS"}:
        if success and event.metadata.state_claim is not None:
            return _EffectiveState(
                event.metadata.state_claim,
                event.metadata.state_claim_source or f"{event_type} claim",
                0.55,
                False,
            )
        return None
    return None


def _detect_recreation(
    link: LinkedResource,
    observations: tuple[EvidenceObservation, ...],
    events: tuple[SystemActivity, ...],
    audit_at: datetime,
) -> tuple[RecreationStatus, list[StateConflict], list[tuple[StateBasis, SystemActivity | EvidenceObservation]]]:
    deletion_events = [
        event
        for event in events
        if event.event_type == "DELETE_RECORD"
        and event.reported_result == ReportedResult.SUCCESS
    ]
    if not deletion_events:
        return RecreationStatus.NONE, [], []

    recreation_events = [
        event
        for event in events
        if event.event_type in _RECREATION_EVENT_TYPES
        and event.reported_result in {ReportedResult.SUCCESS, ReportedResult.PARTIAL}
    ]
    recreation_observations = [
        observation
        for observation in observations
        if _effective_observation_state(observation).state == ObservedState.PRESENT
        and (observation.observed_at or observation.captured_at) > deletion_events[0].event_time
    ]

    conflicts: list[StateConflict] = []
    basis: list[tuple[StateBasis, SystemActivity | EvidenceObservation]] = []
    status = RecreationStatus.NONE
    for deletion in deletion_events:
        later_events = [event for event in recreation_events if event.event_time > deletion.event_time]
        later_observations = [
            observation
            for observation in recreation_observations
            if (observation.observed_at or observation.captured_at) > deletion.event_time
        ]
        if not later_events and not later_observations:
            continue
        if later_events and later_observations:
            status = RecreationStatus.CONFIRMED
        elif status != RecreationStatus.CONFIRMED:
            status = RecreationStatus.SUSPECTED
        source_ids = (
            deletion.activity_id,
            *(event.activity_id for event in later_events),
            *(observation.observation_id for observation in later_observations),
        )
        conflicts.append(
            StateConflict(
                resource_id=link.resource_id,
                description="Record recreated after a successful deletion",
                competing_states=(ObservedState.ABSENT, ObservedState.PRESENT),
                source_ids=source_ids,
                resolution=ObservedState.PRESENT,
                rule=(
                    "A later synchronization/index/restore event or a later PRESENT "
                    "observation contradicts the deletion claim"
                ),
            )
        )
        basis.append(
            (
                StateBasis(
                    source_type="ACTIVITY",
                    source_id=deletion.activity_id,
                    timestamp=deletion.event_time,
                    state=ObservedState.ABSENT,
                    detail="Successful deletion claim",
                    location=deletion.event_type,
                    confidence=0.6,
                ),
                deletion,
            )
        )
        if later_events:
            latest_event = max(later_events, key=lambda event: (event.event_time, event.activity_id))
            basis.append(
                (
                    StateBasis(
                        source_type="ACTIVITY",
                        source_id=latest_event.activity_id,
                        timestamp=latest_event.event_time,
                        state=ObservedState.PRESENT,
                        detail=f"{latest_event.event_type} after successful deletion",
                        location=latest_event.event_type,
                        confidence=0.55,
                    ),
                    latest_event,
                )
            )
    return status, conflicts, basis


def _evidence_basis(observation: EvidenceObservation, decision: _EffectiveState) -> StateBasis:
    location = observation.provenance.location
    location_text = (
        location.json_path
        or (f"table:{location.table},row:{location.row_number}" if location.table else None)
        or (f"line:{location.line_number}" if location.line_number else None)
    )
    return StateBasis(
        source_type="EVIDENCE",
        source_id=observation.observation_id,
        timestamp=observation.observed_at or observation.captured_at,
        state=decision.state,
        detail=decision.rule,
        location=location_text,
        confidence=decision.confidence,
    )


def _activity_basis(event: SystemActivity, claim: _EffectiveState) -> StateBasis:
    return StateBasis(
        source_type="ACTIVITY",
        source_id=event.activity_id,
        timestamp=event.event_time,
        state=claim.state,
        detail=claim.rule,
        location=event.event_type,
        confidence=claim.confidence,
    )


def _dedupe_basis(items: list[StateBasis]) -> list[StateBasis]:
    seen: set[tuple[str, str, str]] = set()
    result: list[StateBasis] = []
    for item in items:
        key = (item.source_type, item.source_id, item.detail)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
