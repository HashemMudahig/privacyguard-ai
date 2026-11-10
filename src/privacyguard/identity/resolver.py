"""Identity resolution on top of :class:`IdentityIndex`."""

from __future__ import annotations

from ..io.types import DatasetFile
from ..models import (
    DeletionRequest,
    IdentifierKind,
    IdentityResolution,
    ProvenanceRef,
    RequestIdentityResolution,
    ResolutionMethod,
    ResolutionStatus,
)
from ..normalization import IdentifierKindError, infer_kind, normalize
from .index import IdentityIndex


def _dedupe_refs(refs: list[ProvenanceRef] | tuple[ProvenanceRef, ...]) -> tuple[ProvenanceRef, ...]:
    seen: set[tuple[str, int, str, str, str | None]] = set()
    result: list[ProvenanceRef] = []
    for ref in refs:
        key = (ref.source_file, ref.row_number, ref.field, ref.value, ref.note)
        if key in seen:
            continue
        seen.add(key)
        result.append(ref)
    return tuple(result)


_METHOD_BY_KIND: dict[tuple[IdentifierKind, bool], ResolutionMethod] = {
    (IdentifierKind.EMAIL, True): ResolutionMethod.CURRENT_EMAIL,
    (IdentifierKind.EMAIL, False): ResolutionMethod.HISTORICAL_EMAIL,
    (IdentifierKind.PHONE, True): ResolutionMethod.CURRENT_PHONE,
    (IdentifierKind.PHONE, False): ResolutionMethod.HISTORICAL_PHONE,
    (IdentifierKind.EMAIL_HASH, True): ResolutionMethod.CURRENT_EMAIL_HASH,
    (IdentifierKind.EMAIL_HASH, False): ResolutionMethod.HISTORICAL_EMAIL_HASH,
}


class IdentityResolver:
    """Resolve identifiers without guessing.

    A lookup that matches more than one ``user_id`` is reported as
    ``AMBIGUOUS`` and no identity is selected.
    """

    def __init__(self, index: IdentityIndex) -> None:
        self.index = index

    def resolve_identifier(
        self,
        value: str,
        kind: IdentifierKind | str | None = None,
    ) -> IdentityResolution:
        if kind is None:
            resolved_kind = IdentifierKind(infer_kind(value))
        elif isinstance(kind, str):
            try:
                resolved_kind = IdentifierKind(kind)
            except ValueError as exc:
                raise IdentifierKindError(
                    f"Unsupported identifier kind: {kind!r}"
                ) from exc
        else:
            resolved_kind = kind

        normalized = normalize(value, resolved_kind.value)
        current_hits = self.index.current_hits(resolved_kind, normalized)
        historical_hits = self.index.historical_hits(resolved_kind, normalized)

        current_users = {hit.user_id for hit in current_hits}
        historical_users = {hit.user_id for hit in historical_hits}
        users = sorted(current_users | historical_users)

        if not users:
            return IdentityResolution(
                status=ResolutionStatus.NOT_FOUND,
                identifier=value,
                normalized_identifier=normalized,
                kind=resolved_kind,
                warnings=(
                    f"No current or historical {resolved_kind.value} match in the dataset",
                ),
            )

        if len(users) > 1:
            all_hits = (*current_hits, *historical_hits)
            return IdentityResolution(
                status=ResolutionStatus.AMBIGUOUS,
                identifier=value,
                normalized_identifier=normalized,
                kind=resolved_kind,
                candidates=tuple(users),
                resolution_provenance=_dedupe_refs(
                    [hit.provenance for hit in all_hits]
                ),
                warnings=(
                    f"Identifier matches {len(users)} user_ids; refusing to guess",
                ),
            )

        user_id = users[0]
        matched_current = user_id in current_users
        method = _METHOD_BY_KIND[(resolved_kind, matched_current)]
        hits = current_hits if matched_current else historical_hits
        provenance = _dedupe_refs([hit.provenance for hit in hits])
        matched_value = provenance[0].value if provenance else value

        warnings: list[str] = []
        if matched_current and user_id in historical_users:
            warnings.append("Identifier also appears in audit history")
        if not matched_current:
            warnings.append(
                "Resolved through a historical audit value; the current "
                "identity may use a different value"
            )

        identity = self.index.build_identity(user_id)
        warnings.extend(identity.warnings)

        return IdentityResolution(
            status=ResolutionStatus.RESOLVED,
            identifier=value,
            normalized_identifier=normalized,
            kind=resolved_kind,
            method=method,
            matched_value=matched_value,
            user_id=user_id,
            identity=identity,
            resolution_provenance=provenance,
            warnings=tuple(warnings),
        )

    def resolve_email(self, email: str) -> IdentityResolution:
        return self.resolve_identifier(email, IdentifierKind.EMAIL)

    def resolve_requests(
        self, requests: DatasetFile[DeletionRequest]
    ) -> tuple[RequestIdentityResolution, ...]:
        return tuple(
            RequestIdentityResolution(
                case_id=row.record.case_id,
                request_email=row.record.email,
                resolution=self.resolve_email(row.record.email),
            )
            for row in requests.rows
        )
