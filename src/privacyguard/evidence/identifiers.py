"""Shared identifier extraction, state mapping and attribute helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..normalization import looks_like_email, looks_like_email_hash, looks_like_phone
from .models import ObservedState

USER_ID_KEYS = {
    "user_id",
    "customer_reference",
    "owner_user_id",
    "customer_id",
}
SUBJECT_REFERENCE_KEYS = {"subject_ref", "subject_reference", "subject_selector"}
EMAIL_KEYS = {
    "email",
    "owner_email",
    "requester_email",
    "customer_email",
    "subject_email",
    "contact_email",
}
PHONE_KEYS = {
    "phone",
    "owner_phone",
    "requester_phone",
    "customer_phone",
    "contact_phone",
}
HASH_KEYS = {"email_hash", "emailhash"}
CLASSIFY_KEYS = {
    "lookup_key",
    "match_key",
    "subject_key",
    "correlation_key",
    "contact_key",
    "identifier",
    "matched_value",
}
RELATED_KEYS = {
    "source_resource_id",
    "ticket_id",
    "audit_id",
}

_STATE_BY_TOKEN: dict[str, ObservedState] = {
    "FOUND": ObservedState.PRESENT,
    "EXISTS": ObservedState.PRESENT,
    "IDENTIFIABLE": ObservedState.PRESENT,
    "PRESENT": ObservedState.PRESENT,
    "HIT": ObservedState.PRESENT,
    "NOT_FOUND": ObservedState.ABSENT,
    "ABSENT": ObservedState.ABSENT,
    "MISSING": ObservedState.ABSENT,
    "DELETED": ObservedState.ABSENT,
    "REDACTED": ObservedState.REDACTED,
    "ANONYMIZED": ObservedState.ANONYMIZED,
    "ACTIVE": ObservedState.ACTIVE,
    "ENABLED": ObservedState.ACTIVE,
    "DISABLED": ObservedState.DISABLED,
    "INACTIVE": ObservedState.DISABLED,
    "BLOCKED": ObservedState.BLOCKED,
}

_ABSENT_HTTP = {404, 410}
_PRESENT_HTTP = {200, 201, 202, 203, 204}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _text(value)
    if text is None:
        return None
    lowered = text.lower()
    if lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    return None


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    text = _text(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _append_unique(target: list[str], seen: set[str], value: str | None) -> None:
    if value is None:
        return
    text = value.strip()
    if not text or text.lower() in {"null", "none", "no direct identifier"}:
        return
    if text in seen:
        return
    seen.add(text)
    target.append(text)


@dataclass
class IdentifierBuckets:
    """Deduplicated identifier values extracted from one source record."""

    user_ids: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    email_hashes: list[str] = field(default_factory=list)
    related_resource_ids: list[str] = field(default_factory=list)
    _seen: dict[str, set[str]] = field(default_factory=dict, repr=False)

    def _seen_for(self, bucket: str) -> set[str]:
        return self._seen.setdefault(bucket, set())

    def add_user_id(self, value: Any) -> None:
        _append_unique(self.user_ids, self._seen_for("user"), _text(value))

    def add_email(self, value: Any) -> None:
        text = _text(value)
        if text and looks_like_email(text):
            _append_unique(self.emails, self._seen_for("email"), text)

    def add_phone(self, value: Any) -> None:
        text = _text(value)
        if text and looks_like_phone(text):
            _append_unique(self.phones, self._seen_for("phone"), text)

    def add_email_hash(self, value: Any) -> None:
        text = _text(value)
        if text:
            _append_unique(self.email_hashes, self._seen_for("hash"), text)

    def add_related_resource(self, value: Any) -> None:
        _append_unique(
            self.related_resource_ids,
            self._seen_for("related"),
            _text(value),
        )

    def classify_and_add(self, value: Any) -> None:
        text = _text(value)
        if text is None:
            return
        if looks_like_email(text):
            self.add_email(text)
        elif looks_like_email_hash(text):
            self.add_email_hash(text)
        elif text.startswith("user_"):
            self.add_user_id(text)
        elif looks_like_phone(text):
            self.add_phone(text)

    def add_keyed_value(self, key: str, value: Any) -> None:
        lowered = key.lower()
        if lowered in USER_ID_KEYS:
            self.add_user_id(value)
        elif lowered in SUBJECT_REFERENCE_KEYS:
            self.classify_and_add(value)
        elif lowered in EMAIL_KEYS:
            self.add_email(value)
        elif lowered in PHONE_KEYS:
            self.add_phone(value)
        elif lowered in HASH_KEYS:
            self.add_email_hash(value)
        elif lowered in CLASSIFY_KEYS:
            self.classify_and_add(value)
        elif lowered in RELATED_KEYS:
            self.add_related_resource(value)

    def merge(self, other: "IdentifierBuckets") -> None:
        for value in other.user_ids:
            self.add_user_id(value)
        for value in other.emails:
            self.add_email(value)
        for value in other.phones:
            self.add_phone(value)
        for value in other.email_hashes:
            self.add_email_hash(value)
        for value in other.related_resource_ids:
            self.add_related_resource(value)


def extract_identifiers(value: Any, buckets: IdentifierBuckets | None = None) -> IdentifierBuckets:
    """Recursively extract identifiers and related references from JSON-like data."""
    if buckets is None:
        buckets = IdentifierBuckets()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                buckets.add_keyed_value(key, child)
            if isinstance(child, (Mapping, list)):
                extract_identifiers(child, buckets)
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, (Mapping, list)):
                extract_identifiers(child, buckets)
    return buckets


def extract_row_identifiers(row: Mapping[str, Any]) -> IdentifierBuckets:
    buckets = IdentifierBuckets()
    for key, value in row.items():
        buckets.add_keyed_value(str(key), value)
    return buckets


def first_resource_id(*records: Mapping[str, Any] | None) -> str | None:
    for record in records:
        if not record:
            continue
        value = _text(record.get("resource_id"))
        if value:
            return value
    return None


def scalar_attributes(record: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return top-level scalar attributes suitable for JSON serialization."""
    if not record:
        return {}
    result: dict[str, Any] = {}
    for key, value in record.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            result[str(key)] = value
    return result


def excerpt(text: str, limit: int = 300) -> str:
    compact = " ".join(text.strip().split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."


def derive_state(
    fields: Mapping[str, Any],
    *,
    event: str | None = None,
) -> tuple[ObservedState, str | None]:
    """Map only explicit source fields to an observed state.

    This function does not infer deletion outcomes. It recognizes a small set
    of explicit state tokens and HTTP/row-count evidence commonly present in the
    supplied files.
    """
    lowered = {str(key).lower(): value for key, value in fields.items()}

    for key in ("result", "state", "record_state", "status"):
        if key not in lowered:
            continue
        token = _text(lowered[key])
        if token is None:
            continue
        mapped = _STATE_BY_TOKEN.get(token.upper())
        if mapped is not None:
            return mapped, key

    for key in ("http_status", "status_code", "http_status_code"):
        if key not in lowered:
            continue
        code = _to_int(lowered[key])
        if code is None:
            continue
        if code in _PRESENT_HTTP:
            return ObservedState.PRESENT, key
        if code in _ABSENT_HTTP:
            return ObservedState.ABSENT, key

    for key in ("enabled",):
        if key in lowered:
            flag = _to_bool(lowered[key])
            if flag is not None:
                return (ObservedState.ACTIVE if flag else ObservedState.DISABLED), key

    for key in ("restore_allowed", "restore_available"):
        if key in lowered:
            flag = _to_bool(lowered[key])
            if flag is not None:
                return (ObservedState.ACTIVE if flag else ObservedState.BLOCKED), key

    if event and "restore" in event.lower():
        eligible = _to_bool(lowered.get("eligible"))
        deletion_block = _to_bool(lowered.get("deletion_block"))
        if deletion_block is True:
            return ObservedState.BLOCKED, "deletion_block"
        if eligible is True and deletion_block is False:
            return ObservedState.ACTIVE, "eligible"
        if eligible is False:
            return ObservedState.BLOCKED, "eligible"

    if "rows" in lowered and event:
        event_lower = event.lower()
        if any(token in event_lower for token in ("lookup_completed", "query_completed", "read_completed", "scan_completed")):
            rows = _to_int(lowered["rows"])
            if rows is not None:
                return (
                    ObservedState.ABSENT if rows == 0 else ObservedState.PRESENT,
                    "rows",
                )

    return ObservedState.UNKNOWN, None
