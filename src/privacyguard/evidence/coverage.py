"""Snapshot coverage and absence-proof models.

A snapshot can prove absence only when it declares a complete collection scope.
Partial replica captures, subject-scoped bundles and inventory captures without
an explicit subject universe do not prove absence.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..models import parse_timestamp
from .models import EvidenceFormat, EvidenceManifestEntry, coerce_timestamp


class SnapshotScopeType(StrEnum):
    COMPLETE_COLLECTION = "COMPLETE_COLLECTION"
    SUBJECT_SCOPED = "SUBJECT_SCOPED"
    INVENTORY_CAPTURE = "INVENTORY_CAPTURE"
    REPLICA_CAPTURE = "REPLICA_CAPTURE"
    SNAPSHOT_BUNDLE = "SNAPSHOT_BUNDLE"
    UNKNOWN = "UNKNOWN"


class SnapshotCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    file_id: str
    file_path: str
    captured_at: datetime
    system_id: str | None
    collection: str | None
    table: str | None = None
    record_count: int = 0
    resource_ids: tuple[str, ...] = ()
    scope_type: SnapshotScopeType
    is_complete: bool
    completeness_reason: str
    provenance: str


class AbsenceStatus(StrEnum):
    PROVEN = "PROVEN"
    PRESENT = "PRESENT"
    NO_COMPLETE_SNAPSHOT = "NO_COMPLETE_SNAPSHOT"
    AMBIGUOUS = "AMBIGUOUS"


class SnapshotAbsenceProof(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_id: str
    system_id: str | None
    collection: str | None
    captured_at: datetime
    file_id: str
    file_path: str
    scope_type: SnapshotScopeType
    confidence: float = Field(ge=0.0, le=1.0, default=0.95)
    reason: str
    provenance: str


class AbsenceQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: AbsenceStatus
    resource_id: str
    system_id: str | None
    collection: str | None
    proof: SnapshotAbsenceProof | None = None
    reason: str


_TABLE_MAPPING = {
    "customer_profiles": ("account_service", "customer_profiles"),
    "customer_profiles_primary": ("account_service", "customer_profiles"),
    "customer_profiles_failover_replica": ("account_service", "customer_profiles"),
    "customer_search_documents": ("search_service", "customer_search_documents"),
    "search_documents_primary": ("search_service", "customer_search_documents"),
    "customer_analytics_profiles": ("analytics_platform", "customer_analytics_profiles"),
    "support_records": ("support_platform", "support_records"),
    "customer_exports": ("export_service", "customer_exports"),
    "connector_subscriptions": ("integration_service", "connector_subscriptions"),
    "backup_restore_entries": ("backup_service", "backup_restore_entries"),
    "security_audit_records": ("security_service", "security_audit_records"),
}
_JSON_RECORD_TABLES = {
    "customer_data_primary",
    "customer_data_read_replica",
    "customer_data_replica_ap_south",
    "customer_data_replica_eu_west",
    "customer_data_reporting_replica",
    "customer_data_failover_replica",
}


class SnapshotCoverageIndex:
    def __init__(self, coverages: tuple[SnapshotCoverage, ...]) -> None:
        self.coverages = coverages

    @classmethod
    def from_dataset(
        cls,
        dataset_dir: str | Path,
        entries: tuple[EvidenceManifestEntry, ...],
    ) -> "SnapshotCoverageIndex":
        root = Path(dataset_dir).resolve()
        coverages: list[SnapshotCoverage] = []
        for entry in entries:
            if entry.format == EvidenceFormat.SQL:
                coverages.extend(cls._sql_coverages(entry))
            elif entry.format == EvidenceFormat.JSON:
                coverages.extend(cls._json_coverages(entry))
        return cls(tuple(coverages))

    @staticmethod
    def _sql_coverages(entry: EvidenceManifestEntry) -> list[SnapshotCoverage]:
        try:
            text = entry.resolved_path.read_text(encoding="utf-8-sig")
            connection = sqlite3.connect(":memory:")
            connection.executescript(text)
        except Exception:
            return []
        coverages: list[SnapshotCoverage] = []
        try:
            tables = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]
            has_scope = "snapshot_scope" in tables
            header = text[:500].lower()
            if "topology: primary_only" in header or "topology: primary" in header:
                topology = "primary"
            elif "topology:" in header:
                topology = "replica"
            else:
                topology = "unknown"
            for table in tables:
                if table == "snapshot_scope":
                    continue
                try:
                    rows = connection.execute(
                        f'SELECT * FROM "{table.replace(chr(34), chr(34) * 2)}"'
                    ).fetchall()
                    columns = [
                        row[1]
                        for row in connection.execute(
                            f'PRAGMA table_info("{table.replace(chr(34), chr(34) * 2)}")'
                        )
                    ]
                except sqlite3.Error:
                    continue
                records = [dict(zip(columns, row)) for row in rows]
                if table in _JSON_RECORD_TABLES:
                    grouped: dict[tuple[str | None, str | None], set[str]] = defaultdict(set)
                    for record in records:
                        payload = record.get("record_json")
                        parsed = {}
                        if isinstance(payload, str):
                            try:
                                parsed = json.loads(payload)
                            except json.JSONDecodeError:
                                parsed = {}
                        resource_id = parsed.get("resource_id") or record.get("resource_id")
                        if resource_id:
                            grouped[
                                (
                                    record.get("origin_system"),
                                    record.get("collection_name"),
                                )
                            ].add(str(resource_id))
                    for (system_id, collection), resource_ids in grouped.items():
                        coverages.append(
                            _coverage(
                                entry,
                                system_id=system_id,
                                collection=collection,
                                table=table,
                                resource_ids=resource_ids,
                                scope_type=(
                                    SnapshotScopeType.REPLICA_CAPTURE
                                    if topology == "replica"
                                    else SnapshotScopeType.INVENTORY_CAPTURE
                                ),
                                reason=(
                                    "Replica capture has no explicit complete subject universe"
                                    if topology == "replica"
                                    else "Capture has no explicit complete subject universe"
                                ),
                            )
                        )
                else:
                    system_id, collection = _TABLE_MAPPING.get(table, (None, table))
                    resource_ids = {
                        str(record.get("resource_id"))
                        for record in records
                        if record.get("resource_id")
                    }
                    coverages.append(
                        _coverage(
                            entry,
                            system_id=system_id,
                            collection=collection,
                            table=table,
                            resource_ids=resource_ids,
                            scope_type=(
                                SnapshotScopeType.INVENTORY_CAPTURE
                                if has_scope
                                else SnapshotScopeType.REPLICA_CAPTURE
                            ),
                            reason=(
                                "Inventory capture does not declare a complete subject universe"
                                if has_scope
                                else "Capture does not declare complete collection scope"
                            ),
                        )
                    )
        finally:
            connection.close()
        return coverages

    @staticmethod
    def _json_coverages(entry: EvidenceManifestEntry) -> list[SnapshotCoverage]:
        try:
            payload = json.loads(entry.resolved_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        snapshots = payload.get("snapshots") if isinstance(payload, dict) else None
        if not isinstance(snapshots, list):
            return []
        coverages: list[SnapshotCoverage] = []
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                continue
            records = snapshot.get("records")
            if not isinstance(records, list):
                continue
            resource_ids = {
                str(record.get("resource_id"))
                for record in records
                if isinstance(record, dict) and record.get("resource_id")
            }
            captured = snapshot.get("captured_at") or entry.captured_at
            try:
                captured_at = parse_timestamp(captured)
            except Exception:
                captured_at = entry.captured_at
            coverages.append(
                SnapshotCoverage(
                    file_id=entry.file_id,
                    file_path=entry.file_path,
                    captured_at=captured_at,
                    system_id=snapshot.get("data_store"),
                    collection=snapshot.get("collection"),
                    table=None,
                    record_count=len(records),
                    resource_ids=tuple(sorted(resource_ids)),
                    scope_type=SnapshotScopeType.SNAPSHOT_BUNDLE,
                    is_complete=False,
                    completeness_reason=(
                        "Snapshot bundle does not declare a complete collection or subject universe"
                    ),
                    provenance=f"{entry.file_id}:{snapshot.get('data_store')}/{snapshot.get('collection')}",
                )
            )
        return coverages

    def prove_absence(
        self,
        resource_id: str,
        *,
        system_id: str | None = None,
        collection: str | None = None,
        audit_at: datetime | str | None = None,
    ) -> AbsenceQueryResult:
        cutoff = coerce_timestamp(audit_at)
        candidates = [
            coverage
            for coverage in self.coverages
            if coverage.is_complete
            and (system_id is None or coverage.system_id == system_id)
            and (collection is None or coverage.collection == collection)
            and (cutoff is None or coverage.captured_at <= cutoff)
        ]
        if not candidates:
            return AbsenceQueryResult(
                status=AbsenceStatus.NO_COMPLETE_SNAPSHOT,
                resource_id=resource_id,
                system_id=system_id,
                collection=collection,
                reason=(
                    "No complete authoritative snapshot covers this system/collection "
                    "at or before audit_at"
                ),
            )
        latest_time = max(coverage.captured_at for coverage in candidates)
        latest = [
            coverage for coverage in candidates if coverage.captured_at == latest_time
        ]
        present = [c for c in latest if resource_id in c.resource_ids]
        absent = [c for c in latest if resource_id not in c.resource_ids]
        if present and absent:
            return AbsenceQueryResult(
                status=AbsenceStatus.AMBIGUOUS,
                resource_id=resource_id,
                system_id=system_id,
                collection=collection,
                reason="Complete snapshots at the same timestamp disagree",
            )
        if present:
            return AbsenceQueryResult(
                status=AbsenceStatus.PRESENT,
                resource_id=resource_id,
                system_id=system_id,
                collection=collection,
                reason="The resource is present in the latest complete snapshot",
            )
        chosen = absent[0]
        proof = SnapshotAbsenceProof(
            resource_id=resource_id,
            system_id=chosen.system_id,
            collection=chosen.collection,
            captured_at=chosen.captured_at,
            file_id=chosen.file_id,
            file_path=chosen.file_path,
            scope_type=chosen.scope_type,
            confidence=0.95,
            reason=(
                f"Resource is absent from the complete snapshot {chosen.file_id} "
                f"({chosen.completeness_reason})"
            ),
            provenance=chosen.provenance,
        )
        return AbsenceQueryResult(
            status=AbsenceStatus.PROVEN,
            resource_id=resource_id,
            system_id=system_id,
            collection=collection,
            proof=proof,
            reason=proof.reason,
        )


def _coverage(
    entry: EvidenceManifestEntry,
    *,
    system_id: str | None,
    collection: str | None,
    table: str,
    resource_ids: set[str],
    scope_type: SnapshotScopeType,
    reason: str,
) -> SnapshotCoverage:
    return SnapshotCoverage(
        file_id=entry.file_id,
        file_path=entry.file_path,
        captured_at=entry.captured_at,
        system_id=system_id,
        collection=collection,
        table=table,
        record_count=len(resource_ids),
        resource_ids=tuple(sorted(resource_ids)),
        scope_type=scope_type,
        is_complete=False,
        completeness_reason=reason,
        provenance=f"{entry.file_id}:{table}",
    )
