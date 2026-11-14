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
from ..evidence.models import EvidenceFormat, EvidenceObservation
from ..models import ResolvedIdentity
from ..normalization import normalize
from .models import (
    AccountCandidate,
    LinkLevel,
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
        workflow_start: datetime | str | None = None,
        workflow_end: datetime | str | None = None,
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
            method = (observation.provenance.extraction_method or "").lower()
            multimodal = observation.format == EvidenceFormat.PNG or method.startswith("windows_ocr")
            corroboration_detail: str | None = None
            if multimodal:
                corroborated, corroboration_detail = self._ocr_corroboration(
                    identity, observation, audit_at
                )
                if not corroborated:
                    unresolved.append(
                        UnresolvedResource(
                            resource_id=observation.resource_id,
                            system_id=observation.system_id,
                            reason=corroboration_detail
                            or (
                                "Low-confidence OCR resource ID is not corroborated by "
                                "text evidence or activity"
                            ),
                            observation_ids=(observation.observation_id,),
                        )
                    )
                    continue
            accumulator = self._accumulator(accumulators, observation.resource_id)
            if multimodal:
                link_type = ResourceLinkType.MULTIMODAL_INFERRED
                confidence = 0.6
                verified = False
                warning = (
                    "Linked through low-confidence OCR; verify against corroborating evidence"
                )
                if corroboration_detail:
                    warning = f"{warning} ({corroboration_detail})"
            else:
                confidence = _DIRECT_CONFIDENCE[link_type]
                verified = True
                warning = None
            accumulator.add(
                link_type=link_type,
                confidence=confidence,
                verified=verified,
                system_id=observation.system_id,
                data_category=observation.data_category,
                observation_id=observation.observation_id,
                provenance=_evidence_provenance(observation, confidence),
                warning=warning,
            )
            self._check_ambiguity(observation, identity, accumulator, unresolved)
            if not multimodal:
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
                        link_level=(
                            LinkLevel.CONFIRMED
                            if accumulator.verified
                            else LinkLevel.INFERRED
                        ),
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
        candidates = self._account_candidates(
            workflow_start,
            workflow_end,
            audit_at,
            {resource.resource_id for resource in linked},
        )
        return ResourceLinkResult(
            linked=linked,
            unresolved=tuple(unresolved),
            candidates=candidates,
            warnings=tuple(warnings),
        )

    def _account_candidates(
        self,
        workflow_start,
        workflow_end,
        audit_at,
        linked_ids: set[str],
    ) -> tuple[AccountCandidate, ...]:
        if workflow_start is None or workflow_end is None:
            return ()
        events = self.activity_index.events_in_window(
            workflow_start,
            workflow_end,
            event_types={
                "DELETE_RECORD",
                "SYNC_RECORD",
                "INDEX_RECORD",
                "RESTORE_BACKUP",
                "REDACT_RECORD",
                "ANONYMIZE_RECORD",
                "CHECK_DATA_FLOW",
                "CHECK_RESTORE_ACCESS",
            },
        )
        grouped: dict[str, list[SystemActivity]] = {}
        for event in events:
            if not event.resource_id.startswith("account_"):
                continue
            if event.resource_id in linked_ids:
                continue
            grouped.setdefault(event.resource_id, []).append(event)

        candidates: list[AccountCandidate] = []
        for resource_id, resource_events in sorted(grouped.items()):
            observations = self.evidence_index.observations_for_resource(
                resource_id, audit_at=audit_at
            )
            provenance = [
                _activity_provenance(event, 0.3) for event in resource_events
            ]
            for observation in observations[-2:]:
                provenance.append(
                    _evidence_provenance(
                        observation,
                        0.4,
                        detail=f"Supporting evidence for account candidate {resource_id}",
                    )
                )
            reasons = [
                "Account appears in workflow-window activity without an explicit identity link"
            ]
            if observations:
                reasons.append("At least one evidence observation exists for the candidate account")
            else:
                reasons.append("No evidence observation exists for the candidate account")
            candidates.append(
                AccountCandidate(
                    resource_id=resource_id,
                    system_id=resource_events[0].target_system,
                    level=LinkLevel.CANDIDATE,
                    confidence=0.4 if observations else 0.3,
                    reasons=tuple(reasons),
                    observation_ids=tuple(
                        observation.observation_id for observation in observations
                    ),
                    activity_ids=tuple(
                        event.activity_id for event in resource_events
                    ),
                    event_types=tuple(
                        sorted({event.event_type for event in resource_events})
                    ),
                    provenance=tuple(provenance),
                    warnings=(
                        "CANDIDATE account relationship; not a confirmed identity link",
                    ),
                )
            )
        return tuple(candidates)

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


    def _ocr_corroboration(
        self,
        identity: ResolvedIdentity,
        observation: EvidenceObservation,
        audit_at,
    ) -> tuple[bool, str | None]:
        resource_id = observation.resource_id
        if not resource_id:
            return False, "OCR observation has no resource ID to corroborate"
        if _ocr_identifier_relation(observation, identity) == "conflict":
            return (
                False,
                "OCR observation mixes identifiers from another identity; "
                "the OCR resource link was not trusted",
            )

        neutral: list[str] = []
        conflicts: list[str] = []
        for other in self.evidence_index.observations_for_resource(
            resource_id, audit_at=audit_at
        ):
            if other.observation_id == observation.observation_id:
                continue
            method = (other.provenance.extraction_method or "").lower()
            if other.format == EvidenceFormat.PNG or method.startswith("windows_ocr"):
                continue
            relation = _identifier_relation(other, identity)
            if relation == "match":
                return (
                    True,
                    f"text evidence {other.observation_id} independently identifies "
                    "the same subject",
                )
            if relation == "conflict":
                conflicts.append(f"text evidence {other.observation_id}")
            else:
                neutral.append(f"text evidence {other.observation_id}")

        for event in self.activity_index.events_for_resource(
            resource_id, audit_at=audit_at
        ):
            relation = _activity_relation(event, identity)
            if relation == "match":
                return (
                    True,
                    f"activity {event.activity_id} independently identifies the same subject",
                )
            if relation == "conflict":
                conflicts.append(f"activity {event.activity_id}")
            else:
                neutral.append(f"activity {event.activity_id}")

        for related in self.evidence_index.observations_for_identity(
            identity, audit_at=audit_at, include_resource_neighbors=False
        ):
            method = (related.provenance.extraction_method or "").lower()
            if related.format == EvidenceFormat.PNG or method.startswith("windows_ocr"):
                continue
            if resource_id in related.related_resource_ids:
                return (
                    True,
                    f"historical identity evidence {related.observation_id} "
                    f"references {resource_id}",
                )

        for event in self.activity_index.events_for_identity(identity, audit_at=audit_at):
            if resource_id in event.metadata.related_resource_ids:
                return (
                    True,
                    f"historical identity activity {event.activity_id} references {resource_id}",
                )

        if conflicts and not neutral:
            return (
                False,
                "OCR resource ID is only corroborated by evidence or activity tied to "
                f"a different identity ({', '.join(conflicts[:2])})",
            )
        if conflicts:
            return (
                False,
                "Independent evidence for the OCR resource ID conflicts with the "
                f"resolved identity ({', '.join(conflicts[:2])})",
            )
        if neutral:
            return (
                True,
                "resource ID appears in independent "
                f"{', '.join(neutral[:2])}, but the subject match relies on OCR",
            )
        return (
            False,
            "No independent text evidence or activity corroborates this OCR resource ID",
        )


def _identity_sets(identity: ResolvedIdentity) -> tuple[set[str], set[str], set[str], set[str]]:
    return (
        {identity.user_id} if identity.user_id else set(),
        {normalize(email, "email") for email in identity.all_emails},
        {normalize(phone, "phone") for phone in identity.all_phones},
        {normalize(email_hash, "email_hash") for email_hash in identity.all_email_hashes},
    )


def _identifier_relation(observation: EvidenceObservation, identity: ResolvedIdentity) -> str:
    return _relation(
        set(observation.user_ids),
        {normalize(email, "email") for email in observation.emails},
        {normalize(phone, "phone") for phone in observation.phones},
        {
            normalize(email_hash, "email_hash")
            for email_hash in observation.email_hashes
        },
        identity,
    )


def _ocr_identifier_relation(
    observation: EvidenceObservation, identity: ResolvedIdentity
) -> str:
    users = set(observation.user_ids)
    phones = {normalize(phone, "phone") for phone in observation.phones}
    email_hashes = {
        normalize(email_hash, "email_hash")
        for email_hash in observation.email_hashes
    }
    identity_users, identity_emails, identity_phones, identity_hashes = _identity_sets(
        identity
    )
    matched_emails: set[str] = set()
    foreign_emails: set[str] = set()
    for email in observation.emails:
        normalized = normalize(email, "email")
        if normalized in identity_emails or any(
            _ocr_email_match(normalized, known) for known in identity_emails
        ):
            matched_emails.add(normalized)
        else:
            foreign_emails.add(normalized)
    if (
        not (users or matched_emails or foreign_emails or phones or email_hashes)
    ):
        return "neutral"
    matches = bool(
        users & identity_users
        or matched_emails
        or phones & identity_phones
        or email_hashes & identity_hashes
    )
    foreign = bool(
        (users - identity_users)
        or foreign_emails
        or (phones - identity_phones)
        or (email_hashes - identity_hashes)
    )
    if foreign:
        return "conflict"
    return "match" if matches else "neutral"


_OCR_CONFUSABLE = frozenset("01il2z8b5s6gq")


def _ocr_email_match(value: str, known: str) -> bool:
    if len(value) != len(known):
        return False
    differences = [
        (left, right)
        for left, right in zip(value, known, strict=True)
        if left != right
    ]
    if len(differences) != 1:
        return False
    left, right = differences[0]
    return left in _OCR_CONFUSABLE and right in _OCR_CONFUSABLE


def _activity_relation(event: SystemActivity, identity: ResolvedIdentity) -> str:
    metadata = event.metadata
    return _relation(
        set(metadata.user_ids),
        {normalize(email, "email") for email in metadata.emails},
        {normalize(phone, "phone") for phone in metadata.phones},
        {normalize(email_hash, "email_hash") for email_hash in metadata.email_hashes},
        identity,
    )


def _relation(
    users: set[str],
    emails: set[str],
    phones: set[str],
    email_hashes: set[str],
    identity: ResolvedIdentity,
) -> str:
    if not (users or emails or phones or email_hashes):
        return "neutral"
    identity_users, identity_emails, identity_phones, identity_hashes = _identity_sets(
        identity
    )
    matches = bool(
        users & identity_users
        or emails & identity_emails
        or phones & identity_phones
        or email_hashes & identity_hashes
    )
    foreign = bool(
        (users - identity_users)
        or (emails - identity_emails)
        or (phones - identity_phones)
        or (email_hashes - identity_hashes)
    )
    if foreign:
        return "conflict"
    return "match" if matches else "neutral"


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
