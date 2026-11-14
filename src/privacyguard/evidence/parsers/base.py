"""Parser interfaces and shared observation construction."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from ...models import parse_timestamp
from ..identifiers import IdentifierBuckets, excerpt
from ..models import (
    EvidenceFormat,
    EvidenceLocation,
    EvidenceManifestEntry,
    EvidenceObservation,
    EvidenceProvenance,
    ObservedState,
)


@dataclass(frozen=True, slots=True)
class ParseOutcome:
    """Result of parsing one evidence file."""

    observations: tuple[EvidenceObservation, ...]
    warnings: tuple[str, ...] = ()
    recognized: bool = True
    metadata: dict[str, str] = field(default_factory=dict)


class EvidenceParser(Protocol):
    """Interface implemented by each supported evidence format."""

    format: EvidenceFormat

    def parse(self, entry: EvidenceManifestEntry, dataset_dir: Path) -> ParseOutcome:
        ...


class ObservationBuilder:
    """Build observations with deterministic IDs and file-level provenance."""

    def __init__(self, entry: EvidenceManifestEntry, source_format: EvidenceFormat) -> None:
        self.entry = entry
        self.source_format = source_format
        self._ordinal = 0

    def build(
        self,
        *,
        system_id: str | None,
        resource_id: str | None,
        data_category: str | None,
        observed_state: ObservedState = ObservedState.UNKNOWN,
        state_field: str | None = None,
        identifiers: IdentifierBuckets | None = None,
        related_resource_ids: tuple[str, ...] = (),
        record: dict[str, Any] | None = None,
        attributes: dict[str, Any] | None = None,
        location: EvidenceLocation,
        observed_at: datetime | str | None = None,
        confidence: float = 1.0,
        warnings: tuple[str, ...] = (),
        extraction_method: str | None = None,
        image_width: int | None = None,
        image_height: int | None = None,
    ) -> EvidenceObservation:
        self._ordinal += 1
        buckets = identifiers or IdentifierBuckets()
        resolved_related = list(related_resource_ids)
        for value in buckets.related_resource_ids:
            if value not in resolved_related:
                resolved_related.append(value)

        observed_moment = None
        if observed_at is not None:
            observed_moment = (
                parse_timestamp(observed_at)
                if isinstance(observed_at, str)
                else observed_at
            )

        return EvidenceObservation(
            observation_id=f"{self.entry.file_id}:{self.source_format.value}:{self._ordinal:05d}",
            file_id=self.entry.file_id,
            file_path=self.entry.file_path,
            captured_at=self.entry.captured_at,
            observed_at=observed_moment,
            format=self.source_format,
            system_id=system_id,
            resource_id=resource_id,
            data_category=data_category,
            observed_state=observed_state,
            state_field=state_field,
            user_ids=tuple(buckets.user_ids),
            emails=tuple(buckets.emails),
            phones=tuple(buckets.phones),
            email_hashes=tuple(buckets.email_hashes),
            related_resource_ids=tuple(resolved_related),
            attributes=attributes or {},
            record=record,
            provenance=EvidenceProvenance(
                file_id=self.entry.file_id,
                file_path=self.entry.file_path,
                captured_at=self.entry.captured_at,
                source_format=self.source_format,
                extraction_method=extraction_method,
                image_width=image_width,
                image_height=image_height,
                location=location,
            ),
            confidence=confidence,
            warnings=warnings,
        )


def raw_excerpt(text: str) -> str:
    return excerpt(text, limit=300)
