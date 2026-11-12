"""In-memory evidence index with temporal and identity-aware lookups."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from ..identity.resolver import IdentityResolver
from ..models import DeletionRequest, IdentifierKind, ResolvedIdentity
from ..normalization import normalize
from .models import (
    EvidenceIndexStats,
    EvidenceObservation,
    coerce_timestamp,
)


class EvidenceIndex:
    """Index observations by resource, identity, related resource and time.

    All lookups accept an optional ``audit_at`` cutoff. When provided, only
    observations whose file-level ``captured_at`` is at or before the cutoff are
    returned. The index never mutates observations.
    """

    def __init__(self, observations: tuple[EvidenceObservation, ...] | list[EvidenceObservation]) -> None:
        self.observations: tuple[EvidenceObservation, ...] = tuple(
            sorted(
                observations,
                key=lambda observation: (
                    observation.captured_at,
                    observation.file_id,
                    observation.observation_id,
                ),
            )
        )
        self._by_resource_id: dict[str, list[EvidenceObservation]] = defaultdict(list)
        self._by_user_id: dict[str, list[EvidenceObservation]] = defaultdict(list)
        self._by_email: dict[str, list[EvidenceObservation]] = defaultdict(list)
        self._by_phone: dict[str, list[EvidenceObservation]] = defaultdict(list)
        self._by_email_hash: dict[str, list[EvidenceObservation]] = defaultdict(list)
        self._by_related_resource: dict[str, list[EvidenceObservation]] = defaultdict(list)
        self._by_file_id: dict[str, list[EvidenceObservation]] = defaultdict(list)
        self._by_system: dict[str, list[EvidenceObservation]] = defaultdict(list)
        self._by_category: dict[str, list[EvidenceObservation]] = defaultdict(list)
        self._by_correlation_id: dict[str, list[EvidenceObservation]] = defaultdict(list)
        self._build()

    def _build(self) -> None:
        for observation in self.observations:
            if observation.resource_id:
                self._by_resource_id[observation.resource_id].append(observation)
            for user_id in observation.user_ids:
                self._by_user_id[user_id].append(observation)
            for email in observation.emails:
                self._by_email[normalize(email, "email")].append(observation)
            for phone in observation.phones:
                self._by_phone[normalize(phone, "phone")].append(observation)
            for email_hash in observation.email_hashes:
                self._by_email_hash[normalize(email_hash, "email_hash")].append(observation)
            for related in observation.related_resource_ids:
                self._by_related_resource[related].append(observation)
            self._by_file_id[observation.file_id].append(observation)
            if observation.system_id:
                self._by_system[observation.system_id].append(observation)
            if observation.data_category:
                self._by_category[observation.data_category].append(observation)
            for correlation_id in _correlation_ids(observation):
                self._by_correlation_id[correlation_id].append(observation)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _filter(
        observations: list[EvidenceObservation] | tuple[EvidenceObservation, ...],
        audit_at: datetime | str | None,
    ) -> tuple[EvidenceObservation, ...]:
        cutoff = coerce_timestamp(audit_at)
        if cutoff is None:
            return tuple(observations)
        return tuple(
            observation
            for observation in observations
            if observation.captured_at <= cutoff
        )

    @staticmethod
    def _dedupe(observations: list[EvidenceObservation]) -> tuple[EvidenceObservation, ...]:
        seen: set[str] = set()
        result: list[EvidenceObservation] = []
        for observation in sorted(
            observations,
            key=lambda item: (item.captured_at, item.file_id, item.observation_id),
        ):
            if observation.observation_id in seen:
                continue
            seen.add(observation.observation_id)
            result.append(observation)
        return tuple(result)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------
    def observations_for_resource(
        self,
        resource_id: str,
        *,
        audit_at: datetime | str | None = None,
        include_related: bool = False,
    ) -> tuple[EvidenceObservation, ...]:
        direct = list(self._by_resource_id.get(resource_id, ()))
        if include_related:
            direct.extend(self._by_related_resource.get(resource_id, ()))
        return self._dedupe(list(self._filter(direct, audit_at)))

    def observations_for_user(
        self,
        user_id: str,
        *,
        audit_at: datetime | str | None = None,
    ) -> tuple[EvidenceObservation, ...]:
        return self._dedupe(list(self._filter(self._by_user_id.get(user_id, ()), audit_at)))

    def observations_for_identifier(
        self,
        value: str,
        kind: IdentifierKind | str,
        *,
        audit_at: datetime | str | None = None,
    ) -> tuple[EvidenceObservation, ...]:
        resolved_kind = kind if isinstance(kind, IdentifierKind) else IdentifierKind(kind)
        normalized = normalize(value, resolved_kind.value)
        if resolved_kind == IdentifierKind.EMAIL:
            source = self._by_email
        elif resolved_kind == IdentifierKind.PHONE:
            source = self._by_phone
        else:
            source = self._by_email_hash
        return self._dedupe(list(self._filter(source.get(normalized, ()), audit_at)))

    def observations_for_identity(
        self,
        identity: ResolvedIdentity,
        *,
        audit_at: datetime | str | None = None,
        include_resource_neighbors: bool = True,
    ) -> tuple[EvidenceObservation, ...]:
        matches: list[EvidenceObservation] = []
        matches.extend(self._by_user_id.get(identity.user_id, ()))
        for email in identity.all_emails:
            matches.extend(self._by_email.get(normalize(email, "email"), ()))
        for phone in identity.all_phones:
            matches.extend(self._by_phone.get(normalize(phone, "phone"), ()))
        for email_hash in identity.all_email_hashes:
            matches.extend(
                self._by_email_hash.get(normalize(email_hash, "email_hash"), ())
            )
        direct = self._dedupe(list(self._filter(matches, audit_at)))
        if not include_resource_neighbors:
            return direct

        resource_ids: set[str] = set()
        for observation in direct:
            if observation.resource_id:
                resource_ids.add(observation.resource_id)
            resource_ids.update(observation.related_resource_ids)

        neighbors: list[EvidenceObservation] = list(direct)
        for resource_id in resource_ids:
            neighbors.extend(self._by_resource_id.get(resource_id, ()))
        return self._dedupe(list(self._filter(neighbors, audit_at)))

    def observations_for_request(
        self,
        request: DeletionRequest,
        resolver: IdentityResolver,
        *,
        audit_at: datetime | str | None = None,
    ) -> tuple[EvidenceObservation, ...]:
        cutoff = audit_at if audit_at is not None else request.audit_at
        resolution = resolver.resolve_email(request.email)
        if resolution.identity is not None:
            return self.observations_for_identity(resolution.identity, audit_at=cutoff)
        return self.observations_for_identifier(
            request.email,
            IdentifierKind.EMAIL,
            audit_at=cutoff,
        )

    def observations_for_correlation(
        self,
        correlation_id: str,
        *,
        audit_at: datetime | str | None = None,
    ) -> tuple[EvidenceObservation, ...]:
        return self._dedupe(
            list(self._filter(self._by_correlation_id.get(correlation_id, ()), audit_at))
        )

    def observations_for_file(
        self,
        file_id: str,
        *,
        audit_at: datetime | str | None = None,
    ) -> tuple[EvidenceObservation, ...]:
        return self._dedupe(list(self._filter(self._by_file_id.get(file_id, ()), audit_at)))

    # ------------------------------------------------------------------
    # Temporal views
    # ------------------------------------------------------------------
    def timeline(
        self,
        resource_id: str,
        *,
        audit_at: datetime | str | None = None,
        include_related: bool = False,
    ) -> tuple[EvidenceObservation, ...]:
        observations = self.observations_for_resource(
            resource_id,
            audit_at=audit_at,
            include_related=include_related,
        )
        return tuple(
            sorted(
                observations,
                key=lambda observation: (
                    observation.captured_at,
                    observation.observed_at or observation.captured_at,
                    observation.observation_id,
                ),
            )
        )

    def latest_for_resource(
        self,
        resource_id: str,
        *,
        audit_at: datetime | str | None = None,
    ) -> EvidenceObservation | None:
        timeline = self.timeline(resource_id, audit_at=audit_at)
        return timeline[-1] if timeline else None

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------
    def stats(self) -> EvidenceIndexStats:
        resources = {observation.resource_id for observation in self.observations if observation.resource_id}
        user_ids = {user_id for observation in self.observations for user_id in observation.user_ids}
        emails = {
            normalize(email, "email")
            for observation in self.observations
            for email in observation.emails
        }
        phones = {
            normalize(phone, "phone")
            for observation in self.observations
            for phone in observation.phones
        }
        email_hashes = {
            normalize(email_hash, "email_hash")
            for observation in self.observations
            for email_hash in observation.email_hashes
        }
        systems = {
            observation.system_id for observation in self.observations if observation.system_id
        }
        categories = {
            observation.data_category
            for observation in self.observations
            if observation.data_category
        }
        correlations = {
            correlation_id
            for observation in self.observations
            for correlation_id in _correlation_ids(observation)
        }
        captured = [observation.captured_at for observation in self.observations]
        return EvidenceIndexStats(
            observations=len(self.observations),
            files=len(self._by_file_id),
            resources=len(resources),
            user_ids=len(user_ids),
            emails=len(emails),
            phones=len(phones),
            email_hashes=len(email_hashes),
            systems=len(systems),
            categories=len(categories),
            correlation_ids=len(correlations),
            earliest_captured_at=min(captured) if captured else None,
            latest_captured_at=max(captured) if captured else None,
        )

    def observations_by_system(self, system_id: str) -> tuple[EvidenceObservation, ...]:
        return tuple(self._by_system.get(system_id, ()))

    def observations_by_category(self, category: str) -> tuple[EvidenceObservation, ...]:
        return tuple(self._by_category.get(category, ()))


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
