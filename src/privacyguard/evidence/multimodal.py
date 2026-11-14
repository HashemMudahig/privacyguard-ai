"""Shared extraction helpers for PDF and image evidence.

Extracted strings are treated strictly as data. Nothing from a document or
screenshot is executed or interpreted as instructions.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .identifiers import IdentifierBuckets
from .models import ObservedState

RESOURCE_RE = re.compile(
    r"\b(?:account|search|analytics|support|export|backup|data_flow|cache|"
    r"audit_record|tombstone|marketing|email_delivery|object|legal)_[A-Za-z0-9]+\b"
)
ORDER_RE = re.compile(r"\b(?:ORD|NST|CS|CJX|FIN)-[A-Za-z0-9][A-Za-z0-9-]*\b")
FILE_RE = re.compile(r"\b[\w.-]+\.(?:pdf|zip|jpg|jpeg|png|tar\.zst)\b", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
USER_RE = re.compile(r"\buser_\d+\b")
HASH_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")
PHONE_RE = re.compile(r"\+\d[\d\s\-().]{6,}\d")

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_HUMAN_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+([A-Za-z]{3})[A-Za-z]*\s+(\d{4})\s+"
    r"(\d{1,2})[: ](\d{2})(?::(\d{2}))?\s+UTC\b",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\b"
)
_TIMESTAMP_KEYWORDS = (
    "captured",
    "issued",
    "generated",
    "recorded",
    "recorded_at",
    "executed",
    "last refreshed",
    "last activity",
    "created",
    "last contact",
)

_ORIGIN_SYSTEM = {
    "account_admin_portal": "account_service",
    "account_history_service": "account_history_service",
    "analytics_platform": "analytics_platform",
    "backup_service": "backup_service",
    "customer_export_service": "export_service",
    "downstream_delivery_service": "notification_service",
    "export_service": "export_service",
    "identity_service": "identity_service",
    "integration_admin": "integration_service",
    "legal_retention_service": "legal_service",
    "marketing_platform": "marketing_platform",
    "object_storage": "object_storage",
    "search_index_admin": "search_service",
    "security_service": "security_service",
    "security_audit_service": "security_service",
    "support_platform": "support_platform",
}

_ORIGIN_CATEGORY = {
    "account_admin_portal": "USER_PROFILE",
    "analytics_platform": "ANALYTICS_PROFILE",
    "backup_service": "BACKUP_ARCHIVE",
    "customer_export_service": "USER_EXPORT",
    "export_service": "USER_EXPORT",
    "identity_service": "ACCOUNT_TOMBSTONE",
    "integration_admin": "DATA_FLOW",
    "legal_retention_service": "LEGAL_HOLD_RECORD",
    "marketing_platform": "MARKETING_PROFILE",
    "search_index_admin": "SEARCH_INDEX_ENTRY",
    "security_service": "SECURITY_AUDIT_LOG",
    "security_audit_service": "SECURITY_AUDIT_LOG",
    "support_platform": "SUPPORT_MESSAGE",
}

_PDF_TITLE_CATEGORY = (
    ("DELIVERY ADDRESS CORRECTION REQUEST", "SUPPORT_ATTACHMENT"),
    ("DISPUTED ORDERS AND TAX RECORDS REGISTER", "LEGAL_HOLD_RECORD"),
    ("COMPLIANCE JOURNAL", "SECURITY_AUDIT_LOG"),
    ("SIGNED RECORD EXTRACT", "SECURITY_AUDIT_LOG"),
    ("SECURITY RETENTION", "SECURITY_AUDIT_LOG"),
)


def normalize_ocr_spacing(text: str) -> str:
    """Repair only OCR spacing around identifier markers, never characters."""
    text = re.sub(
        r"\b(account|search|analytics|support|export|backup|data_flow|cache|"
        r"audit_record|tombstone|marketing|email_delivery|object|legal)\s+_\s*",
        r"\1_",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\buser\s+(\d+)\b", r"user_\1", text, flags=re.IGNORECASE)
    return text


def normalize_inline(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\r", "\n").replace("\n", " ")).strip()


def extract_text_identifiers(text: str) -> tuple[IdentifierBuckets, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return (buckets, resource_ids, order_refs, file_names)."""
    buckets = IdentifierBuckets()
    for email in EMAIL_RE.findall(text):
        buckets.add_email(email)
    for user_id in USER_RE.findall(text):
        buckets.add_user_id(user_id)
    for phone in PHONE_RE.findall(text):
        buckets.add_phone(phone)
    for email_hash in HASH_RE.findall(text):
        buckets.add_email_hash(email_hash)
    resources = tuple(dict.fromkeys(RESOURCE_RE.findall(text)))
    orders = tuple(dict.fromkeys(ORDER_RE.findall(text)))
    files = tuple(dict.fromkeys(FILE_RE.findall(text)))
    return buckets, resources, orders, files


def find_timestamps(text: str) -> tuple[datetime, ...]:
    inline = normalize_inline(text)
    values: list[datetime] = []
    for match in _HUMAN_DATE_RE.finditer(inline):
        day, month_name, year, hour, minute, second = match.groups()
        month = _MONTHS.get(month_name.lower()[:3])
        if not month:
            continue
        values.append(
            datetime(
                int(year),
                month,
                int(day),
                int(hour),
                int(minute),
                int(second or 0),
                tzinfo=timezone.utc,
            )
        )
    for match in _ISO_DATE_RE.finditer(inline):
        try:
            moment = datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
        except ValueError:
            continue
        values.append(moment.astimezone(timezone.utc))
    return tuple(dict.fromkeys(values))


def extract_retain_until(text: str) -> datetime | None:
    marker = re.search(r"retain\s+until\s+(.{0,60})", text, re.IGNORECASE)
    if not marker:
        return None
    match = re.search(r"(\d{1,2})\s+([A-Za-z]{3})[A-Za-z]*\s+(\d{4})", marker.group(1))
    if not match:
        return None
    day, month_name, year = match.groups()
    month = _MONTHS.get(month_name.lower()[:3])
    if not month:
        return None
    return datetime(int(year), month, int(day), tzinfo=timezone.utc)


def extract_observation_timestamp(text: str) -> datetime | None:
    inline = normalize_inline(text)
    lowered = inline.lower()
    best: tuple[int, datetime] | None = None
    for keyword in _TIMESTAMP_KEYWORDS:
        start = 0
        while True:
            index = lowered.find(keyword, start)
            if index < 0:
                break
            window = inline[index : index + 120]
            timestamps = find_timestamps(window)
            if timestamps:
                candidate = (index + len(keyword), timestamps[0])
                if best is None or candidate[0] < best[0]:
                    best = candidate
                break
            start = index + len(keyword)
    if best is not None:
        return best[1]
    return None


def system_from_origin(origin: str) -> str | None:
    return _ORIGIN_SYSTEM.get(origin.strip().lower())


def category_from_origin(origin: str) -> str | None:
    return _ORIGIN_CATEGORY.get(origin.strip().lower())


def category_from_pdf_title(title: str, origin: str) -> tuple[str | None, tuple[str, ...]]:
    upper = title.upper()
    for marker, category in _PDF_TITLE_CATEGORY:
        if marker in upper:
            return category, ()
    origin_category = category_from_origin(origin)
    return origin_category, ()


def category_from_image(origin: str, text: str) -> tuple[str | None, tuple[str, ...]]:
    lowered = text.lower()
    origin_key = origin.strip().lower()
    warnings: list[str] = []
    if origin_key in {"support_platform", "object_storage"} and (
        "attachment" in lowered or ".pdf" in lowered or "object" in lowered
    ):
        return "SUPPORT_ATTACHMENT", warnings
    category = category_from_origin(origin)
    if category is None:
        warnings.append("No image category could be established from origin or visible text")
    return category, tuple(warnings)


def image_state(
    text: str,
    category: str | None,
    *,
    has_direct_identifiers: bool,
    has_user_id: bool,
) -> tuple[ObservedState, str | None, tuple[str, ...]]:
    lowered = text.lower()
    warnings: list[str] = []
    if category == "ACCOUNT_TOMBSTONE":
        if has_direct_identifiers:
            return ObservedState.PRESENT, "tombstone page exposes direct identifiers", ()
        return ObservedState.REDACTED, "retained reference with no direct identifiers", ()
    if category == "DATA_FLOW":
        if any(token in lowered for token in ("disabled", "inactive", "paused")):
            return ObservedState.DISABLED, "visible disabled/inactive indicator", ()
        if any(token in lowered for token in ("healthy", "continuous", "enabled", "active", "running")):
            return ObservedState.ACTIVE, "visible active/continuous-sync indicator", ()
        return ObservedState.UNKNOWN, None, ("Data-flow state indicator was not readable",)
    if category == "BACKUP_ARCHIVE":
        if "restore blocked" in lowered or "restore disabled" in lowered or "blocked" in lowered:
            return ObservedState.BLOCKED, "visible blocked indicator", ()
        if "restore allowed" in lowered or "restore permitted" in lowered or "restore enabled" in lowered:
            return ObservedState.ACTIVE, "visible restore-allowed indicator", ()
        if "archive" in lowered or "restore" in lowered:
            return ObservedState.PRESENT, "archive visible; restore permission not explicit", (
                "Backup restore permission is not explicit in the screenshot",
            )
        return ObservedState.UNKNOWN, None, ("Backup state indicator was not readable",)
    if category in {
        "SEARCH_INDEX_ENTRY",
        "USER_PROFILE",
        "SUPPORT_MESSAGE",
        "SUPPORT_ATTACHMENT",
        "USER_EXPORT",
        "SECURITY_AUDIT_LOG",
        "MARKETING_PROFILE",
    }:
        if has_direct_identifiers or has_user_id:
            return ObservedState.PRESENT, "visible record with identifiers", ()
        return ObservedState.UNKNOWN, None, ("Record is visible but contains no readable identifiers",)
    if category in {"ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"}:
        if has_user_id or has_direct_identifiers:
            return ObservedState.PRESENT, "visible attributable analytics record", ()
        if "anonymous" in lowered or "anonymized" in lowered:
            return ObservedState.ANONYMIZED, "visible anonymized indicator", ()
        return ObservedState.UNKNOWN, None, ("Analytics attribution could not be established",)
    if category == "UNKNOWN" or category is None:
        warnings.append("No policy category could be established for this image")
        return ObservedState.UNKNOWN, None, tuple(warnings)
    return ObservedState.UNKNOWN, None, tuple(warnings)
