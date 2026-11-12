"""Resource identity linking.

The linker connects a resolved identity to resources using only explicit
identifiers and explicit references. It never derives account IDs from user IDs
and never treats an activity claim as an independently verified link.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..activity.index import ActivityIndex
from ..activity.models import SystemActivity
from ..evidence.index import EvidenceIndex
from ..evidence.models import EvidenceObservation
from ..models import ResolvedIdentity
from ..normalization import normalize
from .models import (
    LinkProvenance,
    LinkedResource,
    ResourceLinkResult,
    ResourceLinkType,
    UnresolvedResource,
)

_DIRECT_CONFIDENCE: dict[ResourceLinkType, float] = {
    ResourceLinkType.EXPLICIT_USER_ID: 1.0,
    ResourceLinkType.EMAIL: 0.95,
    ResourceLinkType.PHONE: 0.95,
    ResourceLinkType.EMAIL_HASH: 0.95,
}
_RELATED_CONFIDENCE = 0.8
_ACTIVITY_LINK_CONFIDENCE = 0.9
_ACTIVITY_RELATION_CONFIDENCE = 0.7


@dataclass
class _Accumulator:
    resource_id: str
    link_types: set[ResourceLinkType] = field(default_factory=set)
    confidence: float = 0.0
    verified: bool = False
    system_ids: list[str] = field(default_factory=list)
    data_categories: list[str] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    activity_ids: list[str] = field(default_factory=list)
    provenance: list[LinkProvenance] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(
        self,
        *,
        link_type: ResourceLinkType,
        confidence: float,
        verified: bool,
        system_id: str | None = None,
        data_category: str | None = None,
        observation_id: str | None = None,
        activity_id: str | None = None,
        provenance: LinkProvenance | None = None,
        warning: str | None = None,
    ) -> None:
        self.link_types.add(link_type)
        if confidence > self.confidence:
            self.confidence = confidence
        self.verified = self.verified or verified
        if system_id and system_id not in self.system_ids:
            self.system_ids.append(system_id)
        if data_category and data_category not in self.data_categories:
            self.data_categories.append(data_category)
        if observation_id and observation_id not in self.observation_ids:
            self.observation_ids.append(observation_id)
        if activity_id and activity_id not in self.activity_ids:
            self.activity_ids.append(activity_id)
        if provenance is not None:
            key = (
                provenance.source_type,
                provenance.source_id,
                provenance.detail,
                provenance.location,
            )
            if all(
                (item.source_type, item.source_id, item.detail, item.location) != key
                for item in self.provenance
            ):
                self.provenance.append(provenance)
        if warning and warning not in self.warnings:
            self.warnings.append(warning)


class ResourceLinker:
    """Link a resolved identity to resources using evidence and activity."""

    def __init__(self, evidence_index: EvidenceIndex, activity_index: ActivityIndex) -> None:
        self.evidence_index = evidence_index
        self.activity_index = activity_index

    def link(
        self,
        identity: ResolvedIdentity,
        *,
        audit_at: datetime | str | None = None,
    ) -> ResourceLinkResult:
        accumulators: dict[str, _Accumulator] = {}
        unresolved: list[UnresolvedResource] = []
        warnings: list[str] = []

        emails = {normalize(email, "email") for email in identity.all_emails}
        phones = {normalize(phone, "phone") for phone in identity.all_phones}
        email_hashes = {
            normalize(email_hash, "email_hash")
            for email_hash in identity.all_email_hashes
        }

        direct_observations = self.evidence_index.observations_for_identity(
            identity, audit_at=audit_at, include_resource_neighbors=False
        )
        correlation_ids: set[str] = set()
        for observation in direct_observations:
            correlation_ids.update(_correlation_ids(observation))
        for observation in direct_observations:
            link_type = _classify_observation(
                observation, identity, emails, phones, email_hashes
            )
            if link_type is None or not observation.resource_id:
                continue
            accumulator = self._accumulator(accumulators, observation.resource_id)
            confidence = _DIRECT_CONFIDENCE[link_type]
            accumulator.add(
                link_type=link_type,
                confidence=confidence,
                verified=True,
                system_id=observation.system_id,
                data_category=observation.data_category,
                observation_id=observation.observation_id,
                provenance=_evidence_provenance(observation, confidence),
            )
            self._check_ambiguity(observation, identity, accumulator, unresolved)
            for related in observation.related_resource_ids:
                if related == observation.resource_id:
                    continue
                related_acc = self._accumulator(accumulators, related)
                related_acc.add(
                    link_type=ResourceLinkType.RELATED_RESOURCE,
                    confidence=_RELATED_CONFIDENCE,
                    verified=False,
                    observation_id=observation.observation_id,
                    provenance=_evidence_provenance(
                        observation,
                        _RELATED_CONFIDENCE,
                        detail=f"Related resource {related} referenced by {observation.resource_id}",
                    ),
                )
                self._enrich_related(related, audit_at, related_acc)

        for correlation_id in sorted(correlation_ids):
            for observation in self.evidence_index.observations_for_correlation(
                correlation_id, audit_at=audit_at
            ):
                if not observation.resource_id:
                    continue
                accumulator = self._accumulator(accumulators, observation.resource_id)
                accumulator.add(
                    link_type=ResourceLinkType.EVIDENCE_CHAIN,
                    confidence=0.85,
                    verified=False,
                    system_id=observation.system_id,
                    data_category=observation.data_category,
                    observation_id=observation.observation_id,
                    provenance=_evidence_provenance(
                        observation,
                        0.85,
                        detail=f"Linked through shared correlation id {correlation_id}",
                    ),
                    warning=f"Resource linked through correlation id {correlation_id}",
                )

        identity_events = self.activity_index.events_for_identity(
            identity, audit_at=audit_at
        )
        for event in identity_events:
            accumulator = self._accumulator(accumulators, event.resource_id)
            accumulator.add(
                link_type=ResourceLinkType.ACTIVITY_IDENTITY_LINK,
                confidence=_ACTIVITY_LINK_CONFIDENCE,
                verified=False,
                system_id=event.target_system,
                activity_id=event.activity_id,
                provenance=_activity_provenance(event, _ACTIVITY_LINK_CONFIDENCE),
            )
            for related in event.metadata.related_resource_ids:
                if related == event.resource_id:
                    continue
                related_acc = self._accumulator(accumulators, related)
                related_acc.add(
                    link_type=ResourceLinkType.ACTIVITY_RELATIONSHIP,
                    confidence=_ACTIVITY_RELATION_CONFIDENCE,
                    verified=False,
                    system_id=event.target_system,
                    activity_id=event.activity_id,
                    provenance=_activity_provenance(
                        event,
                        _ACTIVITY_RELATION_CONFIDENCE,
                        detail=f"Activity {event.activity_id} references {related}",
                    ),
                )

        for resource_id in tuple(accumulators):
            for event in self.activity_index.events_for_resource(
                resource_id, audit_at=audit_at
            ):
                for related in event.metadata.related_resource_ids:
                    if related == resource_id:
                        continue
                    related_acc = self._accumulator(accumulators, related)
                    related_acc.add(
                        link_type=ResourceLinkType.ACTIVITY_RELATIONSHIP,
                        confidence=_ACTIVITY_RELATION_CONFIDENCE,
                        verified=False,
                        system_id=event.target_system,
                        activity_id=event.activity_id,
                        provenance=_activity_provenance(
                            event,
                            _ACTIVITY_RELATION_CONFIDENCE,
                            detail=f"Activity {event.activity_id} references {related}",
                        ),
                    )

        linked = tuple(
            sorted(
                (
                    LinkedResource(
                        resource_id=accumulator.resource_id,
                        system_ids=tuple(accumulator.system_ids),
                        data_categories=tuple(accumulator.data_categories),
                        link_types=tuple(
                            sorted(accumulator.link_types, key=lambda item: item.value)
                        ),
                        confidence=accumulator.confidence,
                        verified=accumulator.verified,
                        observation_ids=tuple(accumulator.observation_ids),
                        activity_ids=tuple(accumulator.activity_ids),
                        provenance=tuple(accumulator.provenance),
                        warnings=tuple(accumulator.warnings),
                    )
                    for accumulator in accumulators.values()
                ),
                key=lambda resource: (-resource.confidence, resource.resource_id),
            )
        )

        unresolved.extend(
            _dangling_references(
                accumulators, self.evidence_index, self.activity_index, audit_at
            )
        )
        return ResourceLinkResult(
            linked=linked,
            unresolved=tuple(unresolved),
            warnings=tuple(warnings),
        )

    def _accumulator(
        self, accumulators: dict[str, _Accumulator], resource_id: str
    ) -> _Accumulator:
        if resource_id not in accumulators:
            accumulators[resource_id] = _Accumulator(resource_id=resource_id)
        return accumulators[resource_id]

    def _enrich_related(
        self, resource_id: str, audit_at: datetime | str | None, accumulator: _Accumulator
    ) -> None:
        for observation in self.evidence_index.observations_for_resource(
            resource_id, audit_at=audit_at
        ):
            accumulator.add(
                link_type=ResourceLinkType.RELATED_RESOURCE,
                confidence=_RELATED_CONFIDENCE,
                verified=False,
                system_id=observation.system_id,
                data_category=observation.data_category,
                observation_id=observation.observation_id,
                provenance=_evidence_provenance(
                    observation,
                    _RELATED_CONFIDENCE,
                    detail=f"Evidence for related resource {resource_id}",
                ),
            )

    def _check_ambiguity(
        self,
        observation: EvidenceObservation,
        identity: ResolvedIdentity,
        accumulator: _Accumulator,
        unresolved: list[UnresolvedResource],
    ) -> None:
        other_users = set(observation.user_ids) - {identity.user_id}
        if other_users:
            warning = (
                f"Observation {observation.observation_id} references other user_ids: "
                f"{sorted(other_users)}"
            )
            if warning not in accumulator.warnings:
                accumulator.warnings.append(warning)
            unresolved.append(
                UnresolvedResource(
                    resource_id=observation.resource_id,
                    system_id=observation.system_id,
                    reason=warning,
                    observation_ids=(observation.observation_id,),
                )
            )


def _classify_observation(
    observation: EvidenceObservation,
    identity: ResolvedIdentity,
    emails: set[str],
    phones: set[str],
    email_hashes: set[str],
) -> ResourceLinkType | None:
    if identity.user_id in observation.user_ids:
        return ResourceLinkType.EXPLICIT_USER_ID
    if any(normalize(email, "email") in emails for email in observation.emails):
        return ResourceLinkType.EMAIL
    if any(normalize(phone, "phone") in phones for phone in observation.phones):
        return ResourceLinkType.PHONE
    if any(
        normalize(email_hash, "email_hash") in email_hashes
        for email_hash in observation.email_hashes
    ):
        return ResourceLinkType.EMAIL_HASH
    return None


def _evidence_provenance(
    observation: EvidenceObservation,
    confidence: float,
    *,
    detail: str | None = None,
) -> LinkProvenance:
    location = observation.provenance.location
    location_text = (
        location.json_path
        or (
            f"table:{location.table},row:{location.row_number}"
            if location.table
            else None
        )
        or (f"line:{location.line_number}" if location.line_number else None)
    )
    return LinkProvenance(
        source_type="EVIDENCE",
        source_id=observation.observation_id,
        timestamp=observation.observed_at or observation.captured_at,
        detail=detail or f"Evidence observation {observation.observation_id}",
        location=location_text,
        confidence=confidence,
    )


def _activity_provenance(
    event: SystemActivity,
    confidence: float,
    *,
    detail: str | None = None,
) -> LinkProvenance:
    return LinkProvenance(
        source_type="ACTIVITY",
        source_id=event.activity_id,
        timestamp=event.event_time,
        detail=detail or f"Activity {event.activity_id}: {event.event_type}",
        location=event.event_type,
        confidence=confidence,
    )


_CORRELATION_KEYS = (
    "trace_id",
    "traceId",
    "requestId",
    "request_id",
    "correlation_id",
    "correlationId",
)


def _correlation_ids(observation: EvidenceObservation) -> tuple[str, ...]:
    values: list[str] = []
    for key in _CORRELATION_KEYS:
        value = observation.attributes.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in values:
            values.append(text)
    return tuple(values)


def _dangling_references(
    accumulators: dict[str, _Accumulator],
    evidence_index: EvidenceIndex,
    activity_index: ActivityIndex,
    audit_at: datetime | str | None,
) -> list[UnresolvedResource]:
    unresolved: list[UnresolvedResource] = []
    for accumulator in accumulators.values():
        has_evidence = bool(
            evidence_index.observations_for_resource(
                accumulator.resource_id, audit_at=audit_at
            )
        )
        has_activity = bool(
            activity_index.events_for_resource(
                accumulator.resource_id, audit_at=audit_at
            )
        )
        if has_evidence or has_activity:
            continue
        unresolved.append(
            UnresolvedResource(
                resource_id=accumulator.resource_id,
                system_id=accumulator.system_ids[0] if accumulator.system_ids else None,
                reason="Referenced resource has no evidence observations or activity events",
                observation_ids=tuple(accumulator.observation_ids),
                activity_ids=tuple(accumulator.activity_ids),
            )
        )
    return unresolved
