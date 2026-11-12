"""JSON evidence parser.

Supports the concrete top-level shapes observed in the challenge dataset:

- ``{"exported_at", "source", "snapshots": [...]}``
- ``{"exported_at", "region", "service_exports": {...}}``
- ``{"exported_at", "origin", "record_count", "records": [...]}``
- ``{"captured_at", "source", "collection", "records": [...]}``

Unknown top-level shapes are reported as unrecognized rather than guessed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..identifiers import (
    derive_state,
    excerpt,
    extract_identifiers,
    first_resource_id,
    scalar_attributes,
)
from ..models import (
    EvidenceFormat,
    EvidenceLocation,
    EvidenceManifestEntry,
    EvidenceObservation,
    ObservedState,
)
from ..errors import EvidenceParseError
from .base import ObservationBuilder, ParseOutcome


class JsonEvidenceParser:
    format = EvidenceFormat.JSON

    def parse(self, entry: EvidenceManifestEntry, dataset_dir: Path) -> ParseOutcome:
        try:
            text = entry.resolved_path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (OSError, json.JSONDecodeError) as exc:
            raise EvidenceParseError(f"Invalid JSON in {entry.file_path}: {exc}") from exc

        if not isinstance(data, dict):
            return ParseOutcome(
                observations=(),
                warnings=("Top-level JSON value is not an object",),
                recognized=False,
            )

        builder = ObservationBuilder(entry, self.format)
        observations: list[EvidenceObservation] = []
        warnings: list[str] = []
        recognized = False
        metadata: dict[str, str] = {
            "top_level_keys": ",".join(sorted(str(key) for key in data.keys()))
        }
        if isinstance(data.get("exported_at"), str):
            metadata["exported_at"] = data["exported_at"]
        if isinstance(data.get("source"), str):
            metadata["source"] = data["source"]

        snapshots = data.get("snapshots")
        if isinstance(snapshots, list):
            recognized = True
            for snapshot_index, snapshot in enumerate(snapshots):
                if not isinstance(snapshot, dict):
                    warnings.append(f"snapshots[{snapshot_index}] is not an object")
                    continue
                system_id = _text(snapshot.get("data_store"))
                category = _text(snapshot.get("collection"))
                snapshot_time = snapshot.get("captured_at")
                records = snapshot.get("records")
                if not isinstance(records, list):
                    warnings.append(
                        f"snapshots[{snapshot_index}].records is not a list"
                    )
                    continue
                for record_index, record in enumerate(records):
                    observations.append(
                        _build_record(
                            builder,
                            record,
                            system_id=system_id,
                            category=category,
                            observed_at=snapshot_time,
                            json_path=f"snapshots[{snapshot_index}].records[{record_index}]",
                            default_state=ObservedState.PRESENT,
                            warnings=warnings,
                        )
                    )

        service_exports = data.get("service_exports")
        if isinstance(service_exports, dict):
            recognized = True
            for system_id, groups in service_exports.items():
                if not isinstance(groups, dict):
                    warnings.append(f"service_exports[{system_id!r}] is not an object")
                    continue
                for category, records in groups.items():
                    if not isinstance(records, list):
                        warnings.append(
                            f"service_exports[{system_id!r}][{category!r}] is not a list"
                        )
                        continue
                    for record_index, record in enumerate(records):
                        observations.append(
                            _build_record(
                                builder,
                                record,
                                system_id=_text(system_id),
                                category=_text(category),
                                observed_at=None,
                                json_path=(
                                    f"service_exports[{system_id!r}]"
                                    f"[{category!r}][{record_index}]"
                                ),
                                default_state=ObservedState.PRESENT,
                                warnings=warnings,
                            )
                        )

        records = data.get("records")
        if isinstance(records, list):
            recognized = True
            default_system = _text(data.get("source")) or _text(data.get("origin"))
            default_category = _text(data.get("collection"))
            file_time = data.get("captured_at") or data.get("exported_at")
            for record_index, record in enumerate(records):
                observations.append(
                    _build_record(
                        builder,
                        record,
                        system_id=default_system,
                        category=default_category,
                        observed_at=file_time,
                        json_path=f"records[{record_index}]",
                        default_state=ObservedState.PRESENT,
                        warnings=warnings,
                    )
                )

        if not recognized:
            return ParseOutcome(
                observations=(),
                warnings=(
                    "Unrecognized JSON structure; expected snapshots, "
                    "service_exports or records",
                ),
                recognized=False,
                metadata=metadata,
            )

        return ParseOutcome(
            observations=tuple(observations),
            warnings=tuple(warnings),
            recognized=True,
            metadata=metadata,
        )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _build_record(
    builder: ObservationBuilder,
    record: Any,
    *,
    system_id: str | None,
    category: str | None,
    observed_at: Any,
    json_path: str,
    default_state: ObservedState,
    warnings: list[str],
) -> EvidenceObservation:
    if not isinstance(record, dict):
        warnings.append(f"{json_path} is not an object")
        record = {"value": record}

    buckets = extract_identifiers(record)
    resource_id = first_resource_id(record)
    record_system = _text(record.get("system")) or system_id
    record_category = _text(record.get("record_type")) or category
    event = _text(record.get("event"))
    state, state_field = derive_state(record, event=event)
    if state == ObservedState.UNKNOWN:
        state = default_state
        state_field = "record_present"

    record_observed_at = (
        record.get("observed_at")
        or record.get("recorded_at")
        or observed_at
    )

    attributes = scalar_attributes(record)
    attributes["_json_path"] = json_path

    record_warnings: list[str] = []
    if resource_id is None and not (
        buckets.user_ids or buckets.emails or buckets.phones or buckets.email_hashes
    ):
        record_warnings.append("Record has no resource_id or identifiers")

    return builder.build(
        system_id=record_system,
        resource_id=resource_id,
        data_category=record_category,
        observed_state=state,
        state_field=state_field,
        identifiers=buckets,
        record=record,
        attributes=attributes,
        location=EvidenceLocation(
            record_index=None,
            json_path=json_path,
            raw_excerpt=excerpt(json.dumps(record, ensure_ascii=False, default=str)),
        ),
        observed_at=record_observed_at,
        confidence=1.0,
        warnings=tuple(record_warnings),
    )
