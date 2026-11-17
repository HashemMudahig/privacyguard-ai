from datetime import datetime, timezone

from privacyguard.models import parse_timestamp
from privacyguard.smartshop.adapter import activity_from_row, customer_observation
from privacyguard.smartshop.audit import _ts


def test_customer_observation_preserves_provenance_and_scope() -> None:
    row = {
        "customer_id": "CUST-1001",
        "full_name": "Ava Carter",
        "created_at": "2026-01-10T09:00:00Z",
        "current_status": "ACTIVE",
    }
    obs = customer_observation(row)
    assert obs.file_id == "smartshop"
    assert obs.resource_id == "account_CUST-1001"
    assert obs.system_id == "account_service"
    assert obs.user_ids == ("CUST-1001",)
    assert obs.provenance.file_path == "smartshop://customers"


def test_activity_from_row_maps_reported_result() -> None:
    row = {
        "activity_id": "ACT-0001",
        "event_time": "2026-03-03T00:00:00Z",
        "event_type": "DELETE_RECORD",
        "source_system": "deletion_worker",
        "target_system": "account_service",
        "resource_id": "CUST-1001",
        "reported_result": "SUCCESS",
        "details": "delete",
    }
    activity = activity_from_row(row)
    assert activity.activity_id == "ACT-0001"
    assert activity.reported_result.value == "SUCCESS"
    assert activity.resource_id == "CUST-1001"


def test_ts_handles_datetime_objects_and_strings() -> None:
    from datetime import datetime, timezone

    from privacyguard.models import parse_timestamp

    now = datetime(2026, 3, 3, 0, 0, tzinfo=timezone.utc)
    assert _ts(now) is now
    assert _ts("2026-03-03T00:00:00Z") == parse_timestamp("2026-03-03T00:00:00Z")
