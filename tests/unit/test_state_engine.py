"""Unit tests for deterministic temporal state reconstruction."""

from __future__ import annotations

from privacyguard.activity.index import ActivityIndex
from privacyguard.activity.models import SystemActivity
from privacyguard.evidence.index import EvidenceIndex
from privacyguard.evidence.models import (
    EvidenceFormat,
    EvidenceLocation,
    EvidenceObservation,
    EvidenceProvenance,
    ObservedState,
)
from privacyguard.linking.models import LinkedResource, ResourceLinkType
from privacyguard.models import parse_timestamp
from privacyguard.state.engine import StateEngine
from privacyguard.state.models import RecreationStatus


def make_observation(
    observation_id: str,
    captured_at: str,
    *,
    resource_id: str = "account_1",
    state: ObservedState = ObservedState.PRESENT,
    category: str = "USER_PROFILE",
    system_id: str = "account_service",
    user_ids: tuple[str, ...] = ("user_1",),
    emails: tuple[str, ...] = (),
    phones: tuple[str, ...] = (),
    email_hashes: tuple[str, ...] = (),
    attributes: dict | None = None,
    confidence: float = 1.0,
    extraction_method: str | None = None,
    evidence_format: EvidenceFormat = EvidenceFormat.JSON,
) -> EvidenceObservation:
    moment = parse_timestamp(captured_at)
    return EvidenceObservation(
        observation_id=observation_id,
        file_id="ev_test",
        file_path="evidence/test.json",
        captured_at=moment,
        observed_at=moment,
        format=evidence_format,
        system_id=system_id,
        resource_id=resource_id,
        data_category=category,
        observed_state=state,
        state_field="test",
        user_ids=user_ids,
        emails=emails,
        phones=phones,
        email_hashes=email_hashes,
        related_resource_ids=(),
        attributes=attributes or {},
        record={},
        provenance=EvidenceProvenance(
            file_id="ev_test",
            file_path="evidence/test.json",
            captured_at=moment,
            source_format=evidence_format,
            extraction_method=extraction_method,
            location=EvidenceLocation(record_index=1, json_path="records[0]"),
        ),
        confidence=confidence,
        warnings=(),
    )


def make_activity(
    activity_id: str,
    event_time: str,
    event_type: str,
    *,
    resource_id: str = "account_1",
    result: str = "SUCCESS",
    details: str = "",
    source_system: str = "deletion_worker",
    target_system: str = "account_service",
) -> SystemActivity:
    return SystemActivity.model_validate(
        {
            "activity_id": activity_id,
            "event_time": event_time,
            "event_type": event_type,
            "source_system": source_system,
            "target_system": target_system,
            "resource_id": resource_id,
            "reported_result": result,
            "details": details,
        }
    )


def make_link(
    resource_id: str = "account_1",
    *,
    categories: tuple[str, ...] = ("USER_PROFILE",),
) -> LinkedResource:
    return LinkedResource(
        resource_id=resource_id,
        system_ids=("account_service",),
        data_categories=categories,
        link_types=(ResourceLinkType.EMAIL,),
        confidence=0.95,
        verified=True,
    )


def reconstruct(observations, activities, link, audit_at):
    engine = StateEngine(EvidenceIndex(observations), ActivityIndex(activities))
    return engine.reconstruct([link], audit_at)[0]


def test_successful_deletion_then_present_evidence() -> None:
    state = reconstruct(
        [make_observation("obs_1", "2026-01-02T00:00:00Z")],
        [make_activity("activity_1", "2026-01-01T00:00:00Z", "DELETE_RECORD")],
        make_link(),
        "2026-01-03T00:00:00Z",
    )
    assert state.state == ObservedState.PRESENT
    assert state.verified is True
    assert state.recreated is True
    assert state.recreation_status == RecreationStatus.SUSPECTED
    assert any("recreated" in conflict.description.lower() for conflict in state.conflicts)


def test_failed_deletion_then_absent_evidence() -> None:
    state = reconstruct(
        [
            make_observation(
                "obs_1",
                "2026-01-02T00:00:00Z",
                state=ObservedState.ABSENT,
            )
        ],
        [
            make_activity(
                "activity_1",
                "2026-01-01T00:00:00Z",
                "DELETE_RECORD",
                result="FAILED",
            )
        ],
        make_link(),
        "2026-01-03T00:00:00Z",
    )
    assert state.state == ObservedState.ABSENT
    assert state.verified is True
    assert any("differs" in conflict.description for conflict in state.conflicts)


def test_primary_absent_replica_present() -> None:
    state = reconstruct(
        [
            make_observation(
                "obs_primary",
                "2026-01-02T00:00:00Z",
                state=ObservedState.ABSENT,
                attributes={"_table": "customer_profiles_primary"},
            ),
            make_observation(
                "obs_replica",
                "2026-01-02T00:00:00Z",
                state=ObservedState.PRESENT,
                attributes={"_table": "customer_profiles_failover_replica"},
            ),
        ],
        [],
        make_link(),
        "2026-01-03T00:00:00Z",
    )
    assert state.state == ObservedState.PRESENT
    conflict = next(item for item in state.conflicts if "replica" in item.description.lower())
    assert set(conflict.source_ids) == {"obs_primary", "obs_replica"}
    assert set(state.evidence_ids) == {"obs_primary", "obs_replica"}


def test_backup_restore_risk() -> None:
    state = reconstruct(
        [
            make_observation(
                "obs_backup",
                "2026-01-02T00:00:00Z",
                resource_id="backup_1",
                state=ObservedState.ACTIVE,
                category="BACKUP_ARCHIVE",
                system_id="backup_service",
                user_ids=(),
                attributes={"restore_allowed": 1},
            )
        ],
        [],
        make_link("backup_1", categories=("BACKUP_ARCHIVE",)),
        "2026-01-03T00:00:00Z",
    )
    assert state.kind.value == "BACKUP"
    assert state.state == ObservedState.ACTIVE
    assert state.restore_risk is True


def test_active_data_flow() -> None:
    state = reconstruct(
        [
            make_observation(
                "obs_flow",
                "2026-01-02T00:00:00Z",
                resource_id="data_flow_1",
                state=ObservedState.ACTIVE,
                category="DATA_FLOW",
                system_id="integration_service",
                user_ids=(),
            )
        ],
        [],
        make_link("data_flow_1", categories=("DATA_FLOW",)),
        "2026-01-03T00:00:00Z",
    )
    assert state.state == ObservedState.ACTIVE
    assert state.active_data_flow is True


def test_tombstone_without_direct_identifiers_is_redacted() -> None:
    state = reconstruct(
        [
            make_observation(
                "obs_tombstone",
                "2026-01-02T00:00:00Z",
                resource_id="tombstone_1",
                state=ObservedState.PRESENT,
                category="deleted_customer_references",
                system_id="identity_service",
                user_ids=("user_1",),
            )
        ],
        [],
        make_link("tombstone_1", categories=("deleted_customer_references",)),
        "2026-01-03T00:00:00Z",
    )
    assert state.state == ObservedState.REDACTED
    assert state.verified is False
    assert any("inferred" in uncertainty.lower() for uncertainty in state.uncertainties)


def test_tombstone_explicit_null_identifier_fields_are_verified_redaction() -> None:
    state = reconstruct(
        [
            make_observation(
                "obs_tombstone",
                "2026-01-02T00:00:00Z",
                resource_id="tombstone_1",
                state=ObservedState.PRESENT,
                category="deleted_customer_references",
                system_id="identity_service",
                attributes={"name": None, "email": None, "phone": None},
            )
        ],
        [],
        make_link("tombstone_1", categories=("deleted_customer_references",)),
        "2026-01-03T00:00:00Z",
    )
    assert state.state == ObservedState.REDACTED
    assert state.verified is True


def test_support_literal_redaction_marker_is_direct_verified_evidence() -> None:
    state = reconstruct(
        [
            make_observation(
                "obs_support",
                "2026-01-02T00:00:00Z",
                resource_id="support_1",
                state=ObservedState.PRESENT,
                category="SUPPORT_MESSAGE",
                system_id="support_platform",
                attributes={"message_text": "[REDACTED]"},
            )
        ],
        [],
        make_link("support_1", categories=("SUPPORT_MESSAGE",)),
        "2026-01-03T00:00:00Z",
    )
    assert state.state == ObservedState.REDACTED
    assert state.verified is True


def test_support_null_requester_fields_confirm_successful_redaction() -> None:
    state = reconstruct(
        [
            make_observation(
                "obs_support",
                "2026-01-02T00:00:00Z",
                resource_id="support_1",
                state=ObservedState.PRESENT,
                category="SUPPORT_MESSAGE",
                system_id="support_platform",
                attributes={
                    "requester_name": None,
                    "requester_email": None,
                    "requester_phone": None,
                    "message_excerpt": "Customer contacted support about an order.",
                },
            )
        ],
        [
            make_activity(
                "activity_redact",
                "2026-01-02T01:00:00Z",
                "REDACT_RECORD",
                resource_id="support_1",
                target_system="support_platform",
            )
        ],
        make_link("support_1", categories=("SUPPORT_MESSAGE",)),
        "2026-01-03T00:00:00Z",
    )
    assert state.state == ObservedState.REDACTED
    assert state.verified is True


def test_tombstone_with_email_is_present_and_conflicts() -> None:
    state = reconstruct(
        [
            make_observation(
                "obs_tombstone",
                "2026-01-02T00:00:00Z",
                resource_id="tombstone_1",
                state=ObservedState.PRESENT,
                category="deleted_customer_references",
                system_id="identity_service",
                user_ids=("user_1",),
                emails=("a@example.com",),
            )
        ],
        [],
        make_link("tombstone_1", categories=("deleted_customer_references",)),
        "2026-01-03T00:00:00Z",
    )
    assert state.state == ObservedState.PRESENT
    assert any("Tombstone" in conflict.description for conflict in state.conflicts)


def test_support_message_without_direct_identifiers_is_not_assumed_redacted() -> None:
    state = reconstruct(
        [
            make_observation(
                "obs_support",
                "2026-01-02T00:00:00Z",
                resource_id="support_1",
                state=ObservedState.PRESENT,
                category="SUPPORT_MESSAGE",
                system_id="support_platform",
                user_ids=("user_1",),
            )
        ],
        [],
        make_link("support_1", categories=("SUPPORT_MESSAGE",)),
        "2026-01-03T00:00:00Z",
    )
    assert state.state == ObservedState.PRESENT


def test_support_redaction_requires_successful_activity_claim() -> None:
    observation = make_observation(
        "obs_support",
        "2026-01-02T00:00:00Z",
        resource_id="support_1",
        state=ObservedState.PRESENT,
        category="SUPPORT_MESSAGE",
        system_id="support_platform",
        user_ids=("user_1",),
    )
    link = make_link("support_1", categories=("SUPPORT_MESSAGE",))
    failed = reconstruct(
        [observation],
        [make_activity("activity_1", "2026-01-02T01:00:00Z", "REDACT_RECORD", resource_id="support_1", result="FAILED", target_system="support_platform")],
        link,
        "2026-01-03T00:00:00Z",
    )
    assert failed.state == ObservedState.PRESENT

    succeeded = reconstruct(
        [observation],
        [make_activity("activity_2", "2026-01-02T01:00:00Z", "REDACT_RECORD", resource_id="support_1", target_system="support_platform")],
        link,
        "2026-01-03T00:00:00Z",
    )
    assert succeeded.state == ObservedState.REDACTED
    assert succeeded.verified is False


def test_activity_only_claim_is_not_verified() -> None:
    state = reconstruct(
        [],
        [make_activity("activity_1", "2026-01-01T00:00:00Z", "DELETE_RECORD")],
        make_link(),
        "2026-01-03T00:00:00Z",
    )
    assert state.state == ObservedState.ABSENT
    assert state.verified is False
    assert any("reported activity" in uncertainty for uncertainty in state.uncertainties)


def test_missing_evidence_is_unknown_not_absent() -> None:
    state = reconstruct([], [], make_link(), "2026-01-03T00:00:00Z")
    assert state.state == ObservedState.UNKNOWN
    assert state.state != ObservedState.ABSENT
    assert state.confidence == 0.0


def test_evidence_after_audit_is_excluded() -> None:
    state = reconstruct(
        [make_observation("obs_1", "2026-02-01T00:00:00Z")],
        [],
        make_link(),
        "2026-01-15T00:00:00Z",
    )
    assert state.state == ObservedState.UNKNOWN
    assert any("after audit_at" in uncertainty for uncertainty in state.uncertainties)


def test_sync_after_deletion_recreates() -> None:
    state = reconstruct(
        [],
        [
            make_activity("activity_1", "2026-01-01T00:00:00Z", "DELETE_RECORD"),
            make_activity("activity_2", "2026-01-02T00:00:00Z", "SYNC_RECORD"),
        ],
        make_link(),
        "2026-01-03T00:00:00Z",
    )
    assert state.state == ObservedState.PRESENT
    assert state.recreated is True
    assert state.recreation_status == RecreationStatus.SUSPECTED
    assert state.verified is False


def test_check_restore_access_claim_marks_backup_risk() -> None:
    state = reconstruct(
        [],
        [
            make_activity(
                "activity_1",
                "2026-01-01T00:00:00Z",
                "CHECK_RESTORE_ACCESS",
                resource_id="backup_1",
                details="Restore-access check confirmed that archive backup_1 can still be restored.",
                target_system="backup_service",
            )
        ],
        make_link("backup_1", categories=("BACKUP_ARCHIVE",)),
        "2026-01-03T00:00:00Z",
    )
    assert state.state == ObservedState.ACTIVE
    assert state.restore_risk is True
    assert state.verified is False


def test_confirmed_recreation_requires_event_and_evidence() -> None:
    state = reconstruct(
        [make_observation("obs_1", "2026-01-03T00:00:00Z")],
        [
            make_activity("activity_1", "2026-01-01T00:00:00Z", "DELETE_RECORD"),
            make_activity("activity_2", "2026-01-02T00:00:00Z", "SYNC_RECORD"),
        ],
        make_link(),
        "2026-01-04T00:00:00Z",
    )
    assert state.recreated is True
    assert state.recreation_status == RecreationStatus.CONFIRMED


def test_no_recreation_without_deletion_claim() -> None:
    state = reconstruct(
        [make_observation("obs_1", "2026-01-03T00:00:00Z")],
        [make_activity("activity_2", "2026-01-02T00:00:00Z", "SYNC_RECORD")],
        make_link(),
        "2026-01-04T00:00:00Z",
    )
    assert state.recreated is False
    assert state.recreation_status == RecreationStatus.NONE


def test_newer_observation_overrides_older_in_same_source() -> None:
    state = reconstruct(
        [
            make_observation("obs_old", "2026-01-01T00:00:00Z"),
            make_observation("obs_new", "2026-01-02T00:00:00Z", state=ObservedState.ABSENT),
        ],
        [],
        make_link(),
        "2026-01-03T00:00:00Z",
    )
    assert state.state == ObservedState.ABSENT
    assert state.evidence_ids == ("obs_new",)


def test_completed_record_with_direct_identifiers_is_verified_present() -> None:
    state = reconstruct(
        [
            make_observation(
                "obs_support",
                "2026-01-02T00:00:00Z",
                resource_id="support_1",
                state=ObservedState.UNKNOWN,
                category="SUPPORT_MESSAGE",
                system_id="support_platform",
                user_ids=(),
                emails=("a@example.com",),
                attributes={"event": "support_ticket_read_completed"},
            )
        ],
        [],
        make_link("support_1", categories=("SUPPORT_MESSAGE",)),
        "2026-01-03T00:00:00Z",
    )
    assert state.state == ObservedState.PRESENT
    assert state.verified is True


def test_started_record_with_identifier_is_not_marked_present() -> None:
    state = reconstruct(
        [
            make_observation(
                "obs_support",
                "2026-01-02T00:00:00Z",
                resource_id="support_1",
                state=ObservedState.UNKNOWN,
                category="SUPPORT_MESSAGE",
                system_id="support_platform",
                user_ids=(),
                emails=("a@example.com",),
                attributes={"event": "support_ticket_read_started"},
            )
        ],
        [],
        make_link("support_1", categories=("SUPPORT_MESSAGE",)),
        "2026-01-03T00:00:00Z",
    )
    assert state.state == ObservedState.UNKNOWN


def test_low_confidence_ocr_state_is_unverified() -> None:
    state = reconstruct(
        [
            make_observation(
                "obs_ocr",
                "2026-01-02T00:00:00Z",
                resource_id="account_1",
                state=ObservedState.PRESENT,
                confidence=0.6,
                extraction_method="windows_ocr",
                evidence_format=EvidenceFormat.PNG,
            )
        ],
        [],
        make_link(),
        "2026-01-03T00:00:00Z",
    )
    assert state.state == ObservedState.PRESENT
    assert state.confidence <= 0.6
    assert state.verified is False
    assert state.basis


def test_ocr_evidence_after_audit_is_excluded() -> None:
    state = reconstruct(
        [
            make_observation(
                "obs_ocr",
                "2026-02-01T00:00:00Z",
                resource_id="account_1",
                state=ObservedState.PRESENT,
                confidence=0.6,
                extraction_method="windows_ocr",
                evidence_format=EvidenceFormat.PNG,
            )
        ],
        [],
        make_link(),
        "2026-01-15T00:00:00Z",
    )
    assert state.state == ObservedState.UNKNOWN
    assert any("after audit_at" in uncertainty for uncertainty in state.uncertainties)
