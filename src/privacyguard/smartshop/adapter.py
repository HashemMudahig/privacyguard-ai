from __future__ import annotations

from datetime import datetime
from typing import Any

from privacyguard.activity.models import SystemActivity
from privacyguard.evidence.models import (
    EvidenceFormat,
    EvidenceLocation,
    EvidenceObservation,
    EvidenceProvenance,
    ObservedState,
)
from privacyguard.activity.models import ReportedResult
from privacyguard.models import parse_timestamp


def _ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return parse_timestamp(str(value))


def customer_observation(row: dict[str, Any]) -> EvidenceObservation:
    moment = _ts(row["created_at"])
    return EvidenceObservation(
        observation_id=f"smartshop:customers:{row['customer_id']}",
        file_id="smartshop",
        file_path="smartshop://customers",
        captured_at=moment,
        observed_at=moment,
        format=EvidenceFormat.SQL,
        system_id="account_service",
        resource_id=f"account_{row['customer_id']}",
        data_category="USER_PROFILE",
        observed_state=ObservedState.PRESENT,
        user_ids=(str(row["customer_id"]),),
        attributes={"origin": "smartshop.customers", "customer_id": row["customer_id"]},
        record=dict(row),
        provenance=EvidenceProvenance(
            file_id="smartshop",
            file_path="smartshop://customers",
            captured_at=moment,
            source_format=EvidenceFormat.SQL,
            location=EvidenceLocation(table="customers"),
        ),
        confidence=0.9,
    )


def activity_from_row(row: dict[str, Any]) -> SystemActivity:
    return SystemActivity.model_validate(
        {
            "activity_id": row["activity_id"],
            "event_time": row["event_time"],
            "event_type": row["event_type"],
            "source_system": row.get("source_system", "smartshop"),
            "target_system": row.get("target_system", "smartshop"),
            "resource_id": row["resource_id"],
            "reported_result": row["reported_result"],
            "details": row.get("details", ""),
        }
    )
