"""Unit tests for system activity parsing and indexing."""

from __future__ import annotations

from privacyguard.activity.index import ActivityIndex
from privacyguard.activity.models import ReportedResult, SystemActivity
from privacyguard.activity.details import parse_activity_details
from privacyguard.evidence.models import ObservedState


def make_activity(
    activity_id: str,
    event_time: str,
    event_type: str,
    *,
    resource_id: str = "resource_1",
    details: str = "",
    source_system: str = "deletion_worker",
    target_system: str = "account_service",
    reported_result: str = "SUCCESS",
) -> SystemActivity:
    return SystemActivity.model_validate(
        {
            "activity_id": activity_id,
            "event_time": event_time,
            "event_type": event_type,
            "source_system": source_system,
            "target_system": target_system,
            "resource_id": resource_id,
            "reported_result": reported_result,
            "details": details,
        }
    )


def test_link_resource_identity_metadata() -> None:
    metadata = parse_activity_details(
        "Data catalog linked account_1 (account_1) to a@example.com and user_1.",
        "LINK_RESOURCE_IDENTITY",
        "account_1",
    )
    assert metadata.user_ids == ("user_1",)
    assert metadata.emails == ("a@example.com",)
    assert metadata.related_resource_ids == ()
    assert metadata.state_claim is None


def test_system_names_are_not_resource_references() -> None:
    metadata = parse_activity_details(
        "Deletion worker submitted primary profile account_1 to account_service.",
        "DELETE_RECORD",
        "account_1",
    )
    assert metadata.related_resource_ids == ()


def test_check_data_flow_state_claim() -> None:
    metadata = parse_activity_details(
        "Connector status check confirmed that data flow flow_1 remains enabled.",
        "CHECK_DATA_FLOW",
        "flow_1",
    )
    assert metadata.state_claim == ObservedState.ACTIVE
    assert metadata.state_claim_source


def test_check_restore_access_state_claim() -> None:
    metadata = parse_activity_details(
        "Restore-access check confirmed that archive backup_1 can still be restored.",
        "CHECK_RESTORE_ACCESS",
        "backup_1",
    )
    assert metadata.state_claim == ObservedState.ACTIVE


def test_restore_backup_related_resource() -> None:
    metadata = parse_activity_details(
        "Restore job repopulated downstream resource search_4882.",
        "RESTORE_BACKUP",
        "backup_9287",
    )
    assert metadata.related_resource_ids == ("search_4882",)


def test_correlation_ids_are_parsed() -> None:
    metadata = parse_activity_details(
        "connector read trace_id=tr-1 batch=b-7 attempt=2",
        "CHECK_DATA_FLOW",
        "flow_1",
    )
    assert metadata.correlation_ids == {
        "trace_id": "tr-1",
        "batch": "b-7",
        "attempt": "2",
    }


def test_activity_model_injects_metadata() -> None:
    event = make_activity(
        "activity_1",
        "2026-01-01T00:00:00Z",
        "LINK_RESOURCE_IDENTITY",
        resource_id="account_1",
        details="Data catalog linked account_1 to a@example.com and user_1.",
    )
    assert event.metadata.user_ids == ("user_1",)
    assert event.metadata.emails == ("a@example.com",)
    assert event.reported_result == ReportedResult.SUCCESS


def test_activity_index_temporal_and_identity_lookup() -> None:
    events = [
        make_activity(
            "activity_1",
            "2026-01-01T00:00:00Z",
            "LINK_RESOURCE_IDENTITY",
            resource_id="account_1",
            details="Linked account_1 to a@example.com and user_1.",
        ),
        make_activity(
            "activity_2",
            "2026-02-01T00:00:00Z",
            "DELETE_RECORD",
            resource_id="account_1",
        ),
        make_activity(
            "activity_3",
            "2026-03-01T00:00:00Z",
            "DELETE_RECORD",
            resource_id="account_2",
        ),
    ]
    index = ActivityIndex(events)
    assert [event.activity_id for event in index.events_for_resource("account_1")] == [
        "activity_1",
        "activity_2",
    ]
    assert [
        event.activity_id
        for event in index.events_for_resource(
            "account_1", audit_at="2026-01-15T00:00:00Z"
        )
    ] == ["activity_1"]
    assert [event.activity_id for event in index.events_in_window(
        "2026-01-15T00:00:00Z", "2026-02-15T00:00:00Z"
    )] == ["activity_2"]

    from privacyguard.models import UserIdentity

    identity = UserIdentity(
        user_id="user_1",
        name="A",
        email="a@example.com",
        phone="+1 555 000 1111",
        email_hash="a" * 64,
        updated_at="2026-01-01T00:00:00Z",
    )
    from privacyguard.identity.index import IdentityIndex
    from privacyguard.io.types import DatasetFile, LoadedRow
    from pathlib import Path

    identity_index = IdentityIndex(
        DatasetFile(
            path=Path("identities.csv"),
            display_name="identities.csv",
            rows=(LoadedRow(1, identity, {}),),
        ),
        DatasetFile(path=Path("audit.csv"), display_name="audit.csv", rows=()),
    )
    resolved = identity_index.build_identity("user_1")
    assert [event.activity_id for event in index.events_for_identity(resolved)] == [
        "activity_1"
    ]
