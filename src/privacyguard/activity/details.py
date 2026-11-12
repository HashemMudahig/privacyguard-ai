"""Parsing of free-text system activity details.

Only explicitly present values are extracted. No event is interpreted as a
verified resource state here; explicit state tokens become low-confidence
claims for the state engine to weigh against evidence.
"""

from __future__ import annotations

import re

from ..evidence.identifiers import IdentifierBuckets
from ..evidence.models import ObservedState

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_USER_RE = re.compile(r"\buser_\d+\b")
_HASH_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")
_RESOURCE_RE = re.compile(
    r"\b(?:account|search|analytics|support|export|backup|data_flow|cache|"
    r"audit_record|tombstone|marketing|email_delivery|object|legal)_[A-Za-z0-9]+\b"
)
_PAIR_RE = re.compile(
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>\"(?:[^\"\\]|\\.)*\"|[^\s,;]+)"
)
_PHONE_RE = re.compile(r"\+\d[\d\s\-().]{6,}\d")

_CORRELATION_KEYS = {
    "trace_id",
    "traceid",
    "requestid",
    "request_id",
    "batch",
    "seq",
    "correlation_id",
    "job_id",
    "run_id",
    "attempt",
}

_SYSTEM_SUFFIXES = (
    "_service",
    "_platform",
    "_store",
    "_worker",
    "_intake",
    "_management",
    "_catalog",
    "_cluster",
    "_replica",
    "_portal",
    "_admin",
    "_system",
    "_storage",
    "_preview",
)


def parse_activity_details(
    details: str,
    event_type: str,
    resource_id: str,
) -> "ActivityMetadata":
    from .models import ActivityMetadata

    buckets = IdentifierBuckets()
    for email in _EMAIL_RE.findall(details):
        buckets.add_email(email)
    for user_id in _USER_RE.findall(details):
        buckets.add_user_id(user_id)
    for email_hash in _HASH_RE.findall(details):
        buckets.add_email_hash(email_hash)
    for phone in _PHONE_RE.findall(details):
        buckets.add_phone(phone)

    resources = _RESOURCE_RE.findall(details)
    related: list[str] = []
    for resource in resources:
        if _is_system_name(resource):
            continue
        if resource and resource != resource_id and resource not in related:
            related.append(resource)

    correlation_ids: dict[str, str] = {}
    for match in _PAIR_RE.finditer(details):
        key = match.group("key").lower()
        if key in _CORRELATION_KEYS:
            correlation_ids[key] = match.group("value").strip('"')

    state_claim, state_source = _state_claim(event_type, details)

    notes: list[str] = []
    if not buckets.user_ids and not buckets.emails and not buckets.phones and not buckets.email_hashes:
        if event_type not in {"LINK_RESOURCE_IDENTITY", "CLASSIFY_REQUEST"}:
            notes.append("No identity identifiers in details")

    return ActivityMetadata(
        user_ids=tuple(buckets.user_ids),
        emails=tuple(buckets.emails),
        phones=tuple(buckets.phones),
        email_hashes=tuple(buckets.email_hashes),
        related_resource_ids=tuple(related),
        correlation_ids=correlation_ids,
        state_claim=state_claim,
        state_claim_source=state_source,
        notes=tuple(notes),
    )


def _is_system_name(value: str) -> bool:
    lowered = value.lower()
    return lowered.endswith(_SYSTEM_SUFFIXES)


def _state_claim(event_type: str, details: str) -> tuple[ObservedState | None, str | None]:
    lowered = details.lower()
    if event_type == "CHECK_DATA_FLOW":
        if "remains enabled" in lowered or "is enabled" in lowered or "still enabled" in lowered:
            return ObservedState.ACTIVE, "details:remains_enabled"
        if "remains disabled" in lowered or "is disabled" in lowered or "inactive" in lowered:
            return ObservedState.DISABLED, "details:disabled"
    if event_type == "CHECK_RESTORE_ACCESS":
        if "can still be restored" in lowered or "restore is allowed" in lowered:
            return ObservedState.ACTIVE, "details:restore_allowed"
        if "cannot be restored" in lowered or "restore is blocked" in lowered:
            return ObservedState.BLOCKED, "details:restore_blocked"
    return None, None
