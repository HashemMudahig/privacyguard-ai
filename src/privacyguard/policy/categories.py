"""Resolve policy categories from explicit evidence and corroborated hints.

A resource-ID prefix is never used on its own. Prefix hints require a matching
system and are lower-confidence than explicit categories or record content.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..activity.models import SystemActivity
from ..evidence.models import EvidenceObservation
from ..linking.models import LinkedResource
from ..state.models import ResourceState
from .models import CategoryResolution, PolicyCategory

_ALIASES: dict[str, PolicyCategory] = {
    "user_profile": PolicyCategory.USER_PROFILE,
    "user_profile_record": PolicyCategory.USER_PROFILE,
    "customer_profiles": PolicyCategory.USER_PROFILE,
    "customer_profiles_primary": PolicyCategory.USER_PROFILE,
    "customer_profiles_failover_replica": PolicyCategory.USER_PROFILE,
    "profile": PolicyCategory.USER_PROFILE,
    "secondary_identifier": PolicyCategory.SECONDARY_IDENTIFIER,
    "contact_lookup": PolicyCategory.SECONDARY_IDENTIFIER,
    "contact_index": PolicyCategory.SECONDARY_IDENTIFIER,
    "email_registry": PolicyCategory.SECONDARY_IDENTIFIER,
    "search_index_entry": PolicyCategory.SEARCH_INDEX_ENTRY,
    "customer_search_documents": PolicyCategory.SEARCH_INDEX_ENTRY,
    "search_documents_primary": PolicyCategory.SEARCH_INDEX_ENTRY,
    "index_queries": PolicyCategory.SEARCH_INDEX_ENTRY,
    "cache_entry": PolicyCategory.CACHE_ENTRY,
    "cache": PolicyCategory.CACHE_ENTRY,
    "support_message": PolicyCategory.SUPPORT_MESSAGE,
    "support_conversations": PolicyCategory.SUPPORT_MESSAGE,
    "support_records": PolicyCategory.SUPPORT_MESSAGE,
    "tickets": PolicyCategory.SUPPORT_MESSAGE,
    "support_ticket": PolicyCategory.SUPPORT_MESSAGE,
    "support_attachment": PolicyCategory.SUPPORT_ATTACHMENT,
    "ticket_attachments": PolicyCategory.SUPPORT_ATTACHMENT,
    "attachment": PolicyCategory.SUPPORT_ATTACHMENT,
    "analytics_profile": PolicyCategory.ANALYTICS_PROFILE,
    "customer_analytics_profiles": PolicyCategory.ANALYTICS_PROFILE,
    "customer_analytics_reports": PolicyCategory.ANALYTICS_PROFILE,
    "profiles": PolicyCategory.ANALYTICS_PROFILE,
    "analytics_identity_store": PolicyCategory.ANALYTICS_PROFILE,
    "analytics": PolicyCategory.ANALYTICS_PROFILE,
    "product_telemetry": PolicyCategory.PRODUCT_TELEMETRY,
    "telemetry": PolicyCategory.PRODUCT_TELEMETRY,
    "user_export": PolicyCategory.USER_EXPORT,
    "customer_export_jobs": PolicyCategory.USER_EXPORT,
    "exports": PolicyCategory.USER_EXPORT,
    "export": PolicyCategory.USER_EXPORT,
    "marketing_profile": PolicyCategory.MARKETING_PROFILE,
    "marketing": PolicyCategory.MARKETING_PROFILE,
    "email_delivery_log": PolicyCategory.EMAIL_DELIVERY_LOG,
    "email_delivery": PolicyCategory.EMAIL_DELIVERY_LOG,
    "security_audit_log": PolicyCategory.SECURITY_AUDIT_LOG,
    "security_audit_events": PolicyCategory.SECURITY_AUDIT_LOG,
    "security_audit_records": PolicyCategory.SECURITY_AUDIT_LOG,
    "audit_records": PolicyCategory.SECURITY_AUDIT_LOG,
    "audit_record": PolicyCategory.SECURITY_AUDIT_LOG,
    "legal_hold_record": PolicyCategory.LEGAL_HOLD_RECORD,
    "retained_order_records": PolicyCategory.LEGAL_HOLD_RECORD,
    "legal_hold": PolicyCategory.LEGAL_HOLD_RECORD,
    "backup_archive": PolicyCategory.BACKUP_ARCHIVE,
    "backup_catalog": PolicyCategory.BACKUP_ARCHIVE,
    "restore_entries": PolicyCategory.BACKUP_ARCHIVE,
    "backup": PolicyCategory.BACKUP_ARCHIVE,
    "account_tombstone": PolicyCategory.ACCOUNT_TOMBSTONE,
    "deleted_customer_references": PolicyCategory.ACCOUNT_TOMBSTONE,
    "tombstone": PolicyCategory.ACCOUNT_TOMBSTONE,
    "data_flow": PolicyCategory.DATA_FLOW,
    "connector_configurations": PolicyCategory.DATA_FLOW,
    "connectors": PolicyCategory.DATA_FLOW,
}

_PRIORITY: dict[PolicyCategory, int] = {
    PolicyCategory.ACCOUNT_TOMBSTONE: 100,
    PolicyCategory.USER_PROFILE: 95,
    PolicyCategory.SECONDARY_IDENTIFIER: 90,
    PolicyCategory.SEARCH_INDEX_ENTRY: 85,
    PolicyCategory.CACHE_ENTRY: 80,
    PolicyCategory.SUPPORT_ATTACHMENT: 78,
    PolicyCategory.SUPPORT_MESSAGE: 76,
    PolicyCategory.ANALYTICS_PROFILE: 75,
    PolicyCategory.PRODUCT_TELEMETRY: 74,
    PolicyCategory.USER_EXPORT: 70,
    PolicyCategory.MARKETING_PROFILE: 68,
    PolicyCategory.EMAIL_DELIVERY_LOG: 66,
    PolicyCategory.SECURITY_AUDIT_LOG: 64,
    PolicyCategory.LEGAL_HOLD_RECORD: 62,
    PolicyCategory.BACKUP_ARCHIVE: 60,
    PolicyCategory.DATA_FLOW: 58,
    PolicyCategory.UNKNOWN: 0,
}


@dataclass
class _CategoryCandidate:
    category: PolicyCategory
    confidence: float
    source: str
    evidence_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _normalize(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _canonical(value: str | None) -> PolicyCategory | None:
    if not value:
        return None
    return _ALIASES.get(_normalize(value))


def _has_key(value: Any, keys: set[str]) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in keys:
                return True
            if _has_key(child, keys):
                return True
    elif isinstance(value, list):
        return any(_has_key(child, keys) for child in value)
    return False


def _event_of(observation: EvidenceObservation) -> str:
    return str(observation.attributes.get("event") or "").lower()


def resolve_category(
    state: ResourceState,
    link: LinkedResource | None,
    observations: Iterable[EvidenceObservation],
    activity_systems: Iterable[str] = (),
    activity_events: Iterable[SystemActivity] = (),
) -> CategoryResolution:
    observation_list = list(observations)
    activity_event_list = list(activity_events)
    systems = set(state.system_ids)
    if link is not None:
        systems.update(link.system_ids)
    systems.update(activity_systems)
    candidates: list[_CategoryCandidate] = []

    def add(category: PolicyCategory | None, confidence: float, source: str, evidence_ids: list[str] | None = None, warning: str | None = None) -> None:
        if category is None:
            return
        candidates.append(
            _CategoryCandidate(
                category=category,
                confidence=confidence,
                source=source,
                evidence_ids=evidence_ids or [],
                warnings=[warning] if warning else [],
            )
        )

    for category in state.data_categories:
        add(_canonical(category), 1.0, "state_category", warning=None)

    for observation in observation_list:
        category = _canonical(observation.data_category)
        if category is not None:
            add(category, 1.0, "observation_category", [observation.file_id])

        event = _event_of(observation)
        system = observation.system_id or ""
        resource_id = observation.resource_id or ""
        record = observation.record or {}

        if system == "analytics_platform":
            if any(token in event for token in ("contact_lookup", "contact_query", "lookup")) and not _has_key(
                record, {"metrics", "reporting_window", "audience_cohort"}
            ):
                add(
                    PolicyCategory.SECONDARY_IDENTIFIER,
                    0.8,
                    "content:analytics_contact_lookup",
                    [observation.file_id],
                )
            elif _has_key(record, {"metrics", "reporting_window", "audience_cohort"}):
                add(
                    PolicyCategory.ANALYTICS_PROFILE,
                    0.9,
                    "content:analytics_profile_fields",
                    [observation.file_id],
                )

        if system == "support_platform" or resource_id.startswith("support_"):
            if _has_key(record, {"file_name", "attachment", "attachment_name"}) or "attachment" in event:
                add(
                    PolicyCategory.SUPPORT_ATTACHMENT,
                    0.8,
                    "content:support_attachment",
                    [observation.file_id],
                )
            elif (
                _has_key(record, {"message_text", "message_excerpt", "ticket_id"})
                or "support_ticket" in event
                or "message_" in event
            ):
                add(
                    PolicyCategory.SUPPORT_MESSAGE,
                    0.8,
                    "content:support_message",
                    [observation.file_id],
                )

        if system == "identity_service" and resource_id.startswith("tombstone_"):
            add(
                PolicyCategory.ACCOUNT_TOMBSTONE,
                0.9,
                "content:identity_tombstone",
                [observation.file_id],
            )

        # Corroborated system + prefix hints. Neither signal is sufficient alone.
        prefix_hints = (
            ("account_", "account_service", PolicyCategory.USER_PROFILE),
            ("search_", "search_service", PolicyCategory.SEARCH_INDEX_ENTRY),
            ("analytics_", "analytics_platform", PolicyCategory.ANALYTICS_PROFILE),
            ("export_", "export_service", PolicyCategory.USER_EXPORT),
            ("backup_", "backup_service", PolicyCategory.BACKUP_ARCHIVE),
            ("data_flow_", "integration_service", PolicyCategory.DATA_FLOW),
            ("audit_record_", "security_service", PolicyCategory.SECURITY_AUDIT_LOG),
            ("tombstone_", "identity_service", PolicyCategory.ACCOUNT_TOMBSTONE),
            ("cache_", "cache_service", PolicyCategory.CACHE_ENTRY),
            ("marketing_", "marketing_platform", PolicyCategory.MARKETING_PROFILE),
            ("email_delivery_", "email_delivery_service", PolicyCategory.EMAIL_DELIVERY_LOG),
        )
        for prefix, expected_system, category in prefix_hints:
            if resource_id.startswith(prefix) and system == expected_system:
                add(category, 0.7, f"system_prefix:{system}/{prefix}", [observation.file_id])

    if link is not None:
        resource_id = link.resource_id
        general_hints = (
            ("account_", "account_service", PolicyCategory.USER_PROFILE),
            ("search_", "search_service", PolicyCategory.SEARCH_INDEX_ENTRY),
            ("analytics_", "analytics_platform", PolicyCategory.ANALYTICS_PROFILE),
            ("export_", "export_service", PolicyCategory.USER_EXPORT),
            ("backup_", "backup_service", PolicyCategory.BACKUP_ARCHIVE),
            ("data_flow_", "integration_service", PolicyCategory.DATA_FLOW),
            ("audit_record_", "security_service", PolicyCategory.SECURITY_AUDIT_LOG),
            ("tombstone_", "identity_service", PolicyCategory.ACCOUNT_TOMBSTONE),
            ("cache_", "cache_service", PolicyCategory.CACHE_ENTRY),
            ("marketing_", "marketing_platform", PolicyCategory.MARKETING_PROFILE),
            ("email_delivery_", "email_delivery_service", PolicyCategory.EMAIL_DELIVERY_LOG),
        )
        for prefix, expected_system, category in general_hints:
            if resource_id.startswith(prefix) and expected_system in systems:
                add(category, 0.6, f"system_prefix:{expected_system}/{prefix}")

    if link is not None and not observation_list:
        # Activity-only linked resources may still have a system and a stable ID.
        resource_id = link.resource_id
        prefix_hints = (
            ("account_", "account_service", PolicyCategory.USER_PROFILE),
            ("search_", "search_service", PolicyCategory.SEARCH_INDEX_ENTRY),
            ("analytics_", "analytics_platform", PolicyCategory.ANALYTICS_PROFILE),
            ("export_", "export_service", PolicyCategory.USER_EXPORT),
            ("backup_", "backup_service", PolicyCategory.BACKUP_ARCHIVE),
            ("data_flow_", "integration_service", PolicyCategory.DATA_FLOW),
            ("audit_record_", "security_service", PolicyCategory.SECURITY_AUDIT_LOG),
            ("tombstone_", "identity_service", PolicyCategory.ACCOUNT_TOMBSTONE),
            ("cache_", "cache_service", PolicyCategory.CACHE_ENTRY),
            ("marketing_", "marketing_platform", PolicyCategory.MARKETING_PROFILE),
            ("email_delivery_", "email_delivery_service", PolicyCategory.EMAIL_DELIVERY_LOG),
        )
        for prefix, expected_system, category in prefix_hints:
            if resource_id.startswith(prefix) and expected_system in systems:
                add(
                    category,
                    0.6,
                    f"activity_system_prefix:{expected_system}/{prefix}",
                )

    if not candidates:
        return CategoryResolution(
            category=PolicyCategory.UNKNOWN,
            confidence=0.0,
            source="unknown",
            warnings=("Policy category could not be established",),
        )

    candidates.sort(
        key=lambda item: (
            -item.confidence,
            -_PRIORITY[item.category],
            item.source,
        )
    )
    best = candidates[0]
    # Only evidence attached to the selected category may support that category.
    # Aggregating identifiers from losing candidates can cite a source that in
    # fact supports a conflicting classification.
    evidence_ids = tuple(dict.fromkeys(best.evidence_ids))
    warnings: list[str] = []
    distinct = {candidate.category for candidate in candidates}
    if len(distinct) > 1:
        warnings.append(
            "Multiple policy categories were observed: "
            + ", ".join(sorted(category.value for category in distinct))
        )
    return CategoryResolution(
        category=best.category,
        confidence=best.confidence,
        source=best.source,
        evidence_ids=evidence_ids,
        warnings=tuple(warnings),
    )


def observations_by_resource(
    observations: Iterable[EvidenceObservation],
) -> dict[str, list[EvidenceObservation]]:
    grouped: dict[str, list[EvidenceObservation]] = defaultdict(list)
    for observation in observations:
        if observation.resource_id:
            grouped[observation.resource_id].append(observation)
    return grouped
