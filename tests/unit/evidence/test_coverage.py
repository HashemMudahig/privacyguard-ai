"""Unit tests for snapshot coverage and absence proofs."""

from __future__ import annotations

from datetime import datetime, timezone

from privacyguard.evidence.coverage import (
    AbsenceStatus,
    SnapshotCoverage,
    SnapshotCoverageIndex,
    SnapshotScopeType,
)


def coverage(
    *,
    file_id: str = "evidence_1",
    system_id: str = "account_service",
    collection: str = "customer_profiles",
    resource_ids: tuple[str, ...] = ("account_1",),
    captured_at: datetime | None = None,
    is_complete: bool = True,
    scope_type: SnapshotScopeType = SnapshotScopeType.COMPLETE_COLLECTION,
) -> SnapshotCoverage:
    return SnapshotCoverage(
        file_id=file_id,
        file_path=f"evidence/{file_id}.sql",
        captured_at=captured_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        system_id=system_id,
        collection=collection,
        table=collection,
        record_count=len(resource_ids),
        resource_ids=resource_ids,
        scope_type=scope_type,
        is_complete=is_complete,
        completeness_reason=(
            "Snapshot declares a complete collection universe"
            if is_complete
            else "Partial capture has no complete subject universe"
        ),
        provenance=f"{file_id}:{collection}",
    )


def test_complete_snapshot_proves_absence() -> None:
    index = SnapshotCoverageIndex((coverage(),))
    result = index.prove_absence(
        "account_2",
        system_id="account_service",
        collection="customer_profiles",
        audit_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert result.status == AbsenceStatus.PROVEN
    assert result.proof is not None
    assert result.proof.resource_id == "account_2"
    assert result.proof.file_id == "evidence_1"
    assert result.proof.confidence == 0.95


def test_complete_snapshot_proves_presence() -> None:
    index = SnapshotCoverageIndex((coverage(resource_ids=("account_1", "account_2")),))
    result = index.prove_absence("account_1", audit_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert result.status == AbsenceStatus.PRESENT
    assert result.proof is None


def test_partial_snapshot_does_not_prove_absence() -> None:
    index = SnapshotCoverageIndex((coverage(is_complete=False),))
    result = index.prove_absence("account_2", audit_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert result.status == AbsenceStatus.NO_COMPLETE_SNAPSHOT
    assert result.proof is None


def test_snapshot_after_audit_at_is_ignored() -> None:
    index = SnapshotCoverageIndex(
        (coverage(captured_at=datetime(2026, 2, 1, tzinfo=timezone.utc)),)
    )
    result = index.prove_absence("account_2", audit_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert result.status == AbsenceStatus.NO_COMPLETE_SNAPSHOT


def test_conflicting_complete_snapshots_are_ambiguous() -> None:
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    index = SnapshotCoverageIndex(
        (
            coverage(file_id="evidence_1", resource_ids=("account_1",), captured_at=moment),
            coverage(file_id="evidence_2", resource_ids=(), captured_at=moment),
        )
    )
    result = index.prove_absence("account_1", audit_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert result.status == AbsenceStatus.AMBIGUOUS
    assert result.proof is None


def test_replica_capture_is_not_treated_as_complete() -> None:
    index = SnapshotCoverageIndex(
        (
            coverage(
                is_complete=False,
                scope_type=SnapshotScopeType.REPLICA_CAPTURE,
            ),
        )
    )
    result = index.prove_absence("account_2", audit_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert result.status == AbsenceStatus.NO_COMPLETE_SNAPSHOT
