"""In-memory system activity index."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from ..evidence.models import coerce_timestamp
from ..io.types import DatasetFile
from ..models import ResolvedIdentity
from ..normalization import normalize
from .models import ActivityIndexStats, SystemActivity


class ActivityIndex:
    """Index activity events by resource, identity, system, type and time.

    Activity events are always operational claims. The index exposes them for
    corroboration but never upgrades a claim to a verified state.
    """

    def __init__(
        self,
        activities: DatasetFile[SystemActivity]
        | tuple[SystemActivity, ...]
        | list[SystemActivity],
    ) -> None:
        if isinstance(activities, DatasetFile):
            records = tuple(row.record for row in activities.rows)
        else:
            records = tuple(activities)
        self.activities: tuple[SystemActivity, ...] = tuple(
            sorted(records, key=lambda event: (event.event_time, event.activity_id))
        )
        self._by_resource_id: dict[str, list[SystemActivity]] = defaultdict(list)
        self._by_related_resource: dict[str, list[SystemActivity]] = defaultdict(list)
        self._by_user_id: dict[str, list[SystemActivity]] = defaultdict(list)
        self._by_email: dict[str, list[SystemActivity]] = defaultdict(list)
        self._by_phone: dict[str, list[SystemActivity]] = defaultdict(list)
        self._by_email_hash: dict[str, list[SystemActivity]] = defaultdict(list)
        self._by_event_type: dict[str, list[SystemActivity]] = defaultdict(list)
        self._by_source_system: dict[str, list[SystemActivity]] = defaultdict(list)
        self._by_target_system: dict[str, list[SystemActivity]] = defaultdict(list)
        self._build()

    def _build(self) -> None:
        for event in self.activities:
            self._by_resource_id[event.resource_id].append(event)
            for related in event.metadata.related_resource_ids:
                self._by_related_resource[related].append(event)
            for user_id in event.metadata.user_ids:
                self._by_user_id[user_id].append(event)
            for email in event.metadata.emails:
                self._by_email[normalize(email, "email")].append(event)
            for phone in event.metadata.phones:
                self._by_phone[normalize(phone, "phone")].append(event)
            for email_hash in event.metadata.email_hashes:
                self._by_email_hash[normalize(email_hash, "email_hash")].append(event)
            self._by_event_type[event.event_type].append(event)
            self._by_source_system[event.source_system].append(event)
            self._by_target_system[event.target_system].append(event)

    @staticmethod
    def _filter(
        events: list[SystemActivity] | tuple[SystemActivity, ...],
        audit_at: datetime | str | None,
    ) -> tuple[SystemActivity, ...]:
        cutoff = coerce_timestamp(audit_at)
        if cutoff is None:
            return tuple(events)
        return tuple(event for event in events if event.event_time <= cutoff)

    @staticmethod
    def _dedupe(events: list[SystemActivity]) -> tuple[SystemActivity, ...]:
        seen: set[str] = set()
        result: list[SystemActivity] = []
        for event in sorted(events, key=lambda item: (item.event_time, item.activity_id)):
            if event.activity_id in seen:
                continue
            seen.add(event.activity_id)
            result.append(event)
        return tuple(result)

    def events_for_resource(
        self,
        resource_id: str,
        *,
        audit_at: datetime | str | None = None,
        include_related: bool = False,
    ) -> tuple[SystemActivity, ...]:
        events = list(self._by_resource_id.get(resource_id, ()))
        if include_related:
            events.extend(self._by_related_resource.get(resource_id, ()))
        return self._dedupe(list(self._filter(events, audit_at)))

    def events_for_identity(
        self,
        identity: ResolvedIdentity,
        *,
        audit_at: datetime | str | None = None,
    ) -> tuple[SystemActivity, ...]:
        events: list[SystemActivity] = list(self._by_user_id.get(identity.user_id, ()))
        for email in identity.all_emails:
            events.extend(self._by_email.get(normalize(email, "email"), ()))
        for phone in identity.all_phones:
            events.extend(self._by_phone.get(normalize(phone, "phone"), ()))
        for email_hash in identity.all_email_hashes:
            events.extend(self._by_email_hash.get(normalize(email_hash, "email_hash"), ()))
        return self._dedupe(list(self._filter(events, audit_at)))

    def events_in_window(
        self,
        start: datetime | str,
        end: datetime | str,
        *,
        event_types: set[str] | None = None,
    ) -> tuple[SystemActivity, ...]:
        start_at = coerce_timestamp(start)
        end_at = coerce_timestamp(end)
        if start_at is None or end_at is None:
            return ()
        return tuple(
            event
            for event in self.activities
            if start_at <= event.event_time <= end_at
            and (event_types is None or event.event_type in event_types)
        )

    def events_for_type(self, event_type: str) -> tuple[SystemActivity, ...]:
        return tuple(self._by_event_type.get(event_type, ()))

    def latest_for_resource(
        self,
        resource_id: str,
        *,
        audit_at: datetime | str | None = None,
    ) -> SystemActivity | None:
        events = self.events_for_resource(resource_id, audit_at=audit_at)
        return events[-1] if events else None

    def stats(self) -> ActivityIndexStats:
        resources = {event.resource_id for event in self.activities}
        user_ids = {
            user_id for event in self.activities for user_id in event.metadata.user_ids
        }
        emails = {
            normalize(email, "email")
            for event in self.activities
            for email in event.metadata.emails
        }
        phones = {
            normalize(phone, "phone")
            for event in self.activities
            for phone in event.metadata.phones
        }
        email_hashes = {
            normalize(email_hash, "email_hash")
            for event in self.activities
            for email_hash in event.metadata.email_hashes
        }
        timestamps = [event.event_time for event in self.activities]
        return ActivityIndexStats(
            events=len(self.activities),
            resources=len(resources),
            user_ids=len(user_ids),
            emails=len(emails),
            phones=len(phones),
            email_hashes=len(email_hashes),
            event_types=len(self._by_event_type),
            source_systems=len(self._by_source_system),
            target_systems=len(self._by_target_system),
            earliest_event_at=min(timestamps) if timestamps else None,
            latest_event_at=max(timestamps) if timestamps else None,
        )
