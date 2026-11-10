"""In-memory identity index built from current identities and audit history."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..models import (
    AuditEvent,
    AuditField,
    HistoricalValues,
    IdentifierKind,
    ProvenanceRef,
    ResolvedIdentity,
    UserIdentity,
)
from ..normalization import normalize
from ..io.types import DatasetFile, LoadedRow

_FIELD_TO_KIND: dict[AuditField, IdentifierKind] = {
    AuditField.EMAIL: IdentifierKind.EMAIL,
    AuditField.PHONE: IdentifierKind.PHONE,
    AuditField.EMAIL_HASH: IdentifierKind.EMAIL_HASH,
}

_CURRENT_FIELD_BY_KIND: dict[IdentifierKind, str] = {
    IdentifierKind.EMAIL: "email",
    IdentifierKind.PHONE: "phone",
    IdentifierKind.EMAIL_HASH: "email_hash",
}

_IDENTITY_FIELDS = ("user_id", "name", "email", "phone", "email_hash", "updated_at")
_AUDIT_FIELDS = ("audit_id", "user_id", "event_time", "field_name", "old_value", "new_value")


@dataclass(frozen=True, slots=True)
class IndexHit:
    """One identifier observation tied to exactly one provenance record."""

    user_id: str
    kind: IdentifierKind
    normalized_value: str
    provenance: ProvenanceRef


def _dedupe_provenance(
    refs: list[ProvenanceRef] | tuple[ProvenanceRef, ...],
) -> tuple[ProvenanceRef, ...]:
    seen: set[tuple[str, int, str, str, str | None]] = set()
    result: list[ProvenanceRef] = []
    for ref in refs:
        key = (ref.source_file, ref.row_number, ref.field, ref.value, ref.note)
        if key in seen:
            continue
        seen.add(key)
        result.append(ref)
    return tuple(result)


class IdentityIndex:
    """Index current and historical identifiers for exact, provenance-backed lookup.

    The index never guesses a user. If a normalized value maps to more than one
    ``user_id``, callers must treat the lookup as ambiguous.
    """

    def __init__(
        self,
        identities: DatasetFile[UserIdentity],
        audit_events: DatasetFile[AuditEvent],
        *,
        identity_source: str | None = None,
        audit_source: str | None = None,
    ) -> None:
        self.identities = identities
        self.audit_events = audit_events
        self.identity_source = identity_source or identities.display_name
        self.audit_source = audit_source or audit_events.display_name

        self._current_by_user: dict[str, LoadedRow[UserIdentity]] = {}
        self._audit_by_user: dict[str, list[LoadedRow[AuditEvent]]] = defaultdict(list)
        self._provenance_by_user: dict[str, list[ProvenanceRef]] = defaultdict(list)
        self._current_index: dict[IdentifierKind, dict[str, list[IndexHit]]] = {
            kind: defaultdict(list) for kind in IdentifierKind
        }
        self._historical_index: dict[IdentifierKind, dict[str, list[IndexHit]]] = {
            kind: defaultdict(list) for kind in IdentifierKind
        }
        self.build_warnings: list[str] = []
        self._build()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build(self) -> None:
        for row in self.identities.rows:
            identity = row.record
            if identity.user_id in self._current_by_user:
                self.build_warnings.append(
                    f"Duplicate current identity for user_id={identity.user_id}; "
                    f"keeping row {self._current_by_user[identity.user_id].row_number}"
                )
                continue
            self._current_by_user[identity.user_id] = row
            self._provenance_by_user[identity.user_id].extend(
                self._identity_provenance(row)
            )
            for kind in IdentifierKind:
                field = _CURRENT_FIELD_BY_KIND[kind]
                value = getattr(identity, field)
                normalized = normalize(value, kind.value)
                if not normalized:
                    continue
                hit = IndexHit(
                    user_id=identity.user_id,
                    kind=kind,
                    normalized_value=normalized,
                    provenance=ProvenanceRef(
                        source_file=self.identity_source,
                        row_number=row.row_number,
                        record_id=identity.user_id,
                        field=field,
                        value=value,
                    ),
                )
                self._current_index[kind][normalized].append(hit)

        ordered_audit_rows = sorted(
            self.audit_events.rows,
            key=lambda row: (row.record.event_time, row.record.audit_id, row.row_number),
        )
        for row in ordered_audit_rows:
            event = row.record
            self._audit_by_user[event.user_id].append(row)
            self._provenance_by_user[event.user_id].extend(
                self._audit_provenance(row)
            )
            kind = _FIELD_TO_KIND[event.field_name]
            for note, value in (("old_value", event.old_value), ("new_value", event.new_value)):
                normalized = normalize(value, kind.value)
                if not normalized:
                    continue
                hit = IndexHit(
                    user_id=event.user_id,
                    kind=kind,
                    normalized_value=normalized,
                    provenance=ProvenanceRef(
                        source_file=self.audit_source,
                        row_number=row.row_number,
                        record_id=event.audit_id,
                        field=kind.value,
                        value=value,
                        note=note,
                    ),
                )
                self._historical_index[kind][normalized].append(hit)

        self._detect_cross_user_collisions()

    def _identity_provenance(self, row: LoadedRow[UserIdentity]) -> list[ProvenanceRef]:
        return [
            ProvenanceRef(
                source_file=self.identity_source,
                row_number=row.row_number,
                record_id=row.record.user_id,
                field=field,
                value=row.raw.get(field, ""),
            )
            for field in _IDENTITY_FIELDS
        ]

    def _audit_provenance(self, row: LoadedRow[AuditEvent]) -> list[ProvenanceRef]:
        return [
            ProvenanceRef(
                source_file=self.audit_source,
                row_number=row.row_number,
                record_id=row.record.audit_id,
                field=field,
                value=row.raw.get(field, ""),
            )
            for field in _AUDIT_FIELDS
        ]

    def _detect_cross_user_collisions(self) -> None:
        for kind in IdentifierKind:
            for index_name, index in (
                ("current", self._current_index[kind]),
                ("historical", self._historical_index[kind]),
            ):
                for normalized, hits in index.items():
                    users = sorted({hit.user_id for hit in hits})
                    if len(users) > 1:
                        self.build_warnings.append(
                            f"{index_name} {kind.value} collision for a value "
                            f"normalized to {normalized!r}: users {users}"
                        )

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------
    def current_hits(self, kind: IdentifierKind, normalized: str) -> tuple[IndexHit, ...]:
        return tuple(self._current_index[kind].get(normalized, ()))

    def historical_hits(
        self, kind: IdentifierKind, normalized: str
    ) -> tuple[IndexHit, ...]:
        return tuple(self._historical_index[kind].get(normalized, ()))

    def current_identity(self, user_id: str) -> LoadedRow[UserIdentity] | None:
        return self._current_by_user.get(user_id)

    def audit_rows_for_user(self, user_id: str) -> tuple[LoadedRow[AuditEvent], ...]:
        return tuple(self._audit_by_user.get(user_id, ()))

    def provenance_for_user(self, user_id: str) -> tuple[ProvenanceRef, ...]:
        return _dedupe_provenance(self._provenance_by_user.get(user_id, ()))

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------
    def build_identity(self, user_id: str) -> ResolvedIdentity:
        """Build a resolved identity from the current row plus audit history."""
        current_row = self._current_by_user.get(user_id)
        current = current_row.record if current_row else None
        events = self._audit_by_user.get(user_id, ())
        warnings: list[str] = []

        all_values: dict[IdentifierKind, list[tuple[str, str]]] = {
            kind: [] for kind in IdentifierKind
        }
        seen: dict[IdentifierKind, set[str]] = {kind: set() for kind in IdentifierKind}

        def add(kind: IdentifierKind, value: str) -> None:
            normalized = normalize(value, kind.value)
            if not normalized or normalized in seen[kind]:
                return
            seen[kind].add(normalized)
            all_values[kind].append((value, normalized))

        if current is not None:
            add(IdentifierKind.EMAIL, current.email)
            add(IdentifierKind.PHONE, current.phone)
            add(IdentifierKind.EMAIL_HASH, current.email_hash)
        else:
            warnings.append(
                f"No current identity row found in {self.identity_source} for {user_id}"
            )

        for row in events:
            event = row.record
            kind = _FIELD_TO_KIND[event.field_name]
            add(kind, event.old_value)
            add(kind, event.new_value)

        current_normalized = {
            IdentifierKind.EMAIL: normalize(current.email, "email") if current else "",
            IdentifierKind.PHONE: normalize(current.phone, "phone") if current else "",
            IdentifierKind.EMAIL_HASH: (
                normalize(current.email_hash, "email_hash") if current else ""
            ),
        }

        def historical(kind: IdentifierKind) -> tuple[str, ...]:
            return tuple(
                value
                for value, normalized in all_values[kind]
                if normalized != current_normalized[kind]
            )

        warnings.extend(self._identity_specific_warnings(user_id, current, events))

        return ResolvedIdentity(
            user_id=user_id,
            current=current,
            historical=HistoricalValues(
                emails=historical(IdentifierKind.EMAIL),
                phones=historical(IdentifierKind.PHONE),
                email_hashes=historical(IdentifierKind.EMAIL_HASH),
            ),
            all_emails=tuple(value for value, _ in all_values[IdentifierKind.EMAIL]),
            all_phones=tuple(value for value, _ in all_values[IdentifierKind.PHONE]),
            all_email_hashes=tuple(
                value for value, _ in all_values[IdentifierKind.EMAIL_HASH]
            ),
            provenance=self.provenance_for_user(user_id),
            warnings=tuple(warnings),
        )

    def _identity_specific_warnings(
        self,
        user_id: str,
        current: UserIdentity | None,
        events: list[LoadedRow[AuditEvent]] | tuple[LoadedRow[AuditEvent], ...],
    ) -> list[str]:
        warnings: list[str] = []
        if current is None and events:
            warnings.append(
                f"Historical audit events exist for {user_id} without a current identity row"
            )
        return warnings
