"""Plain-text handover record parser."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..errors import EvidenceParseError
from ..identifiers import IdentifierBuckets, derive_state, excerpt
from ..models import (
    EvidenceFormat,
    EvidenceLocation,
    EvidenceManifestEntry,
    EvidenceObservation,
)
from .base import ObservationBuilder, ParseOutcome

_HANDOVER_RE = re.compile(
    r"^-\s*(?P<timestamp>\S+)\s*\|\s*(?P<system>[^|]+?)\s*\|\s*"
    r"(?P<resource>[^|]+?)\s*\|\s*(?P<category>[^|]+?)\s*\|\s*"
    r"(?P<state>[^|]+?)\s*\|\s*(?P<identifier>.+?)\s*$"
)
_SNAPSHOT_RE = re.compile(r"^Snapshot:\s*(?P<timestamp>\S+)\s*$", re.IGNORECASE)


class TxtEvidenceParser:
    format = EvidenceFormat.TXT

    def parse(self, entry: EvidenceManifestEntry, dataset_dir: Path) -> ParseOutcome:
        try:
            text = entry.resolved_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise EvidenceParseError(f"Cannot read text file {entry.file_path}: {exc}") from exc

        builder = ObservationBuilder(entry, EvidenceFormat.TXT)
        observations: list[EvidenceObservation] = []
        warnings: list[str] = []
        metadata: dict[str, str] = {}
        matched_lines = 0

        for line_number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            snapshot = _SNAPSHOT_RE.match(stripped)
            if snapshot:
                metadata["snapshot_timestamp"] = snapshot.group("timestamp")
                continue
            if not stripped.startswith("-"):
                continue

            match = _HANDOVER_RE.match(stripped)
            if not match:
                warnings.append(f"Line {line_number}: unrecognized handover row")
                continue
            matched_lines += 1

            system_id = match.group("system").strip()
            resource_id = match.group("resource").strip()
            category = match.group("category").strip()
            state_token = match.group("state").strip()
            identifier = match.group("identifier").strip()

            state, state_field = derive_state({"state": state_token})
            buckets = IdentifierBuckets()
            if identifier.lower() not in {"no direct identifier", "none", "null"}:
                buckets.classify_and_add(identifier)
                if not (
                    buckets.user_ids
                    or buckets.emails
                    or buckets.phones
                    or buckets.email_hashes
                ):
                    warnings.append(
                        f"Line {line_number}: identifier {identifier!r} was not classifiable"
                    )

            record = {
                "timestamp": match.group("timestamp"),
                "system": system_id,
                "resource_id": resource_id,
                "data_category": category,
                "state": state_token,
                "identifier": identifier,
            }
            observations.append(
                builder.build(
                    system_id=system_id,
                    resource_id=resource_id,
                    data_category=category,
                    observed_state=state,
                    state_field=state_field,
                    identifiers=buckets,
                    record=record,
                    attributes={**record, "_line": line_number},
                    location=EvidenceLocation(
                        line_number=line_number,
                        raw_excerpt=excerpt(line),
                    ),
                    observed_at=match.group("timestamp"),
                    confidence=1.0,
                    warnings=(),
                )
            )

        if matched_lines == 0:
            warnings.append("No structured handover rows were recognized")
            return ParseOutcome(
                observations=(),
                warnings=tuple(warnings),
                recognized=False,
                metadata=metadata,
            )

        return ParseOutcome(
            observations=tuple(observations),
            warnings=tuple(warnings),
            recognized=True,
            metadata=metadata,
        )
