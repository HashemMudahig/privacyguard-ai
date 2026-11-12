"""SQLite-compatible SQL snapshot parser.

Snapshots are executed only inside a fresh in-memory SQLite database. The
parser rejects external-attachment and extension-loading constructs before
execution. Unsupported SQL constructs are reported as parse failures by the
service layer.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from ..errors import EvidenceParseError, UnsupportedSqlConstruct
from ..identifiers import (
    IdentifierBuckets,
    derive_state,
    excerpt,
    extract_identifiers,
    extract_row_identifiers,
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
from .base import ObservationBuilder, ParseOutcome

_FORBIDDEN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bATTACH\b", re.IGNORECASE), "ATTACH"),
    (re.compile(r"\bDETACH\b", re.IGNORECASE), "DETACH"),
    (re.compile(r"\bVACUUM\b", re.IGNORECASE), "VACUUM"),
    (re.compile(r"\bLOAD_EXTENSION\b", re.IGNORECASE), "LOAD_EXTENSION"),
    (re.compile(r"\bREADFILE\b", re.IGNORECASE), "READFILE"),
    (re.compile(r"\bWRITEFILE\b", re.IGNORECASE), "WRITEFILE"),
    (re.compile(r"(?m)^\s*\.\s*(?:read|import|backup|restore)\b", re.IGNORECASE), "SQLite dot-command"),
)

# Schema-based mapping, not case-specific mapping.
_TABLE_MAPPING: dict[str, tuple[str | None, str | None]] = {
    "customer_profiles": ("account_service", "USER_PROFILE"),
    "customer_profiles_primary": ("account_service", "USER_PROFILE"),
    "customer_profiles_failover_replica": ("account_service", "USER_PROFILE"),
    "customer_search_documents": ("search_service", "SEARCH_INDEX_ENTRY"),
    "search_documents_primary": ("search_service", "SEARCH_INDEX_ENTRY"),
    "customer_analytics_profiles": ("analytics_platform", "ANALYTICS_PROFILE"),
    "support_records": ("support_platform", "SUPPORT_MESSAGE"),
    "customer_exports": ("export_service", "USER_EXPORT"),
    "connector_subscriptions": ("integration_service", "DATA_FLOW"),
    "backup_restore_entries": ("backup_service", "BACKUP_ARCHIVE"),
    "security_audit_records": ("security_service", "SECURITY_AUDIT_LOG"),
}

_JSON_RECORD_TABLES = {
    "customer_data_primary",
    "customer_data_read_replica",
    "customer_data_replica_ap_south",
    "customer_data_replica_eu_west",
    "customer_data_reporting_replica",
    "customer_data_failover_replica",
}

_METADATA_TABLES = {"snapshot_scope"}


class SqlEvidenceParser:
    format = EvidenceFormat.SQL

    def parse(self, entry: EvidenceManifestEntry, dataset_dir: Path) -> ParseOutcome:
        try:
            sql_text = entry.resolved_path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise EvidenceParseError(f"Cannot read SQL file {entry.file_path}: {exc}") from exc

        _validate_sql(sql_text)

        topology = _header_value(sql_text, "Database topology")
        snapshot_captured_at = _header_value(sql_text, "Captured at")
        metadata: dict[str, str] = {}
        if topology:
            metadata["database_topology"] = topology
        if snapshot_captured_at:
            metadata["snapshot_captured_at"] = snapshot_captured_at

        try:
            connection = sqlite3.connect(":memory:")
            try:
                connection.executescript(sql_text)
                observations, warnings, table_stats = _read_database(
                    connection, entry, topology
                )
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise EvidenceParseError(f"SQL execution failed for {entry.file_path}: {exc}") from exc

        if table_stats:
            metadata["tables"] = ", ".join(
                f"{name}={rows}" for name, rows in sorted(table_stats.items())
            )

        return ParseOutcome(
            observations=tuple(observations),
            warnings=tuple(warnings),
            recognized=True,
            metadata=metadata,
        )


def _validate_sql(sql_text: str) -> None:
    for pattern, label in _FORBIDDEN_PATTERNS:
        if pattern.search(sql_text):
            raise UnsupportedSqlConstruct(f"Rejected SQL construct: {label}")
    for pragma in re.finditer(r"\bPRAGMA\s+([A-Za-z_][A-Za-z0-9_]*)", sql_text, re.IGNORECASE):
        if pragma.group(1).lower() != "foreign_keys":
            raise UnsupportedSqlConstruct(
                f"Rejected SQL pragma: {pragma.group(1)}"
            )


def _header_value(sql_text: str, label: str) -> str | None:
    match = re.search(
        rf"(?m)^--\s*{re.escape(label)}:\s*(\S+)",
        sql_text,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def _read_database(
    connection: sqlite3.Connection,
    entry: EvidenceManifestEntry,
    topology: str | None,
) -> tuple[list[EvidenceObservation], list[str], dict[str, int]]:
    builder = ObservationBuilder(entry, EvidenceFormat.SQL)
    observations: list[EvidenceObservation] = []
    warnings: list[str] = []
    table_stats: dict[str, int] = {}

    tables = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    ]

    for table in tables:
        if table in _METADATA_TABLES:
            continue
        try:
            columns = [
                row[1]
                for row in connection.execute(f'PRAGMA table_info("{_quote(table)}")')
            ]
            rows = connection.execute(f'SELECT * FROM "{_quote(table)}"').fetchall()
        except sqlite3.Error as exc:
            warnings.append(f"Could not read table {table}: {exc}")
            continue

        table_stats[table] = len(rows)
        system_id, category = _TABLE_MAPPING.get(table, (None, table))
        if table not in _TABLE_MAPPING and table not in _JSON_RECORD_TABLES:
            warnings.append(f"Unmapped SQL table {table!r}; category defaults to table name")

        for row_number, raw_row in enumerate(rows, start=1):
            row = {column: raw_row[index] for index, column in enumerate(columns)}
            if table in _JSON_RECORD_TABLES:
                observation = _build_json_row(
                    builder,
                    row,
                    table=table,
                    row_number=row_number,
                    topology=topology,
                    warnings=warnings,
                )
            else:
                observation = _build_flat_row(
                    builder,
                    row,
                    table=table,
                    system_id=system_id,
                    category=category,
                    row_number=row_number,
                    topology=topology,
                )
            observations.append(observation)

    return observations, warnings, table_stats


def _build_json_row(
    builder: ObservationBuilder,
    row: dict[str, Any],
    *,
    table: str,
    row_number: int,
    topology: str | None,
    warnings: list[str],
) -> EvidenceObservation:
    record_json = row.get("record_json")
    parsed: dict[str, Any] | None = None
    confidence = 1.0
    row_warnings: list[str] = []
    if isinstance(record_json, str):
        try:
            candidate = json.loads(record_json)
            if isinstance(candidate, dict):
                parsed = candidate
            else:
                row_warnings.append("record_json is not a JSON object")
                confidence = 0.5
        except json.JSONDecodeError as exc:
            row_warnings.append(f"Invalid record_json: {exc}")
            confidence = 0.5
    else:
        row_warnings.append("record_json column is missing or not text")
        confidence = 0.5

    system_id = _text(row.get("origin_system")) or _text(
        parsed.get("system") if parsed else None
    )
    category = _text(row.get("collection_name")) or _text(
        parsed.get("record_type") if parsed else None
    )

    buckets = IdentifierBuckets()
    if parsed:
        buckets.merge(extract_identifiers(parsed))
    buckets.merge(extract_row_identifiers(row))

    resource_id = first_resource_id(parsed, row)
    event = _text(parsed.get("event")) if parsed else None
    state, state_field = derive_state(parsed or {}, event=event)
    if state == ObservedState.UNKNOWN:
        state, state_field = derive_state(row)
    if state == ObservedState.UNKNOWN:
        state = ObservedState.PRESENT
        state_field = "row_exists"

    attributes = scalar_attributes(row)
    attributes.pop("record_json", None)
    attributes["_table"] = table
    if topology:
        attributes["_snapshot_topology"] = topology

    observed_at = (
        row.get("updated_at")
        or (parsed.get("observed_at") if parsed else None)
        or (parsed.get("updated_at") if parsed else None)
    )

    warnings.extend(row_warnings)
    return builder.build(
        system_id=system_id,
        resource_id=resource_id,
        data_category=category,
        observed_state=state,
        state_field=state_field,
        identifiers=buckets,
        record=parsed if parsed is not None else row,
        attributes=attributes,
        location=EvidenceLocation(
            table=table,
            row_number=row_number,
            raw_excerpt=excerpt(json.dumps(parsed or row, ensure_ascii=False, default=str)),
        ),
        observed_at=observed_at,
        confidence=confidence,
        warnings=tuple(row_warnings),
    )


def _build_flat_row(
    builder: ObservationBuilder,
    row: dict[str, Any],
    *,
    table: str,
    system_id: str | None,
    category: str | None,
    row_number: int,
    topology: str | None,
) -> EvidenceObservation:
    buckets = extract_row_identifiers(row)
    resource_id = first_resource_id(row)
    state, state_field = derive_state(row)
    if state == ObservedState.UNKNOWN:
        state = ObservedState.PRESENT
        state_field = "row_exists"

    attributes = scalar_attributes(row)
    attributes["_table"] = table
    if topology:
        attributes["_snapshot_topology"] = topology

    record_warnings: list[str] = []
    if resource_id is None:
        record_warnings.append("Row has no resource_id")

    return builder.build(
        system_id=system_id,
        resource_id=resource_id,
        data_category=category,
        observed_state=state,
        state_field=state_field,
        identifiers=buckets,
        record=row,
        attributes=attributes,
        location=EvidenceLocation(
            table=table,
            row_number=row_number,
            raw_excerpt=excerpt(json.dumps(row, ensure_ascii=False, default=str)),
        ),
        observed_at=row.get("updated_at")
        or row.get("indexed_at")
        or row.get("created_at"),
        confidence=1.0,
        warnings=tuple(record_warnings),
    )


def _quote(identifier: str) -> str:
    return identifier.replace('"', '""')


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
