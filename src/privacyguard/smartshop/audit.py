from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from privacyguard.activity.index import ActivityIndex
from privacyguard.context.models import AuditContext
from privacyguard.context.service import _workflow_window
from privacyguard.decision.engine import AuditDecisionEngine
from privacyguard.decision.models import AuditResult
from privacyguard.evidence.index import EvidenceIndex
from privacyguard.evidence.models import (
    EvidenceFormat,
    EvidenceLocation,
    EvidenceObservation,
    EvidenceProvenance,
    ObservedState,
)
from privacyguard.linking.linker import ResourceLinker
from privacyguard.models import (
    DeletionRequest,
    HistoricalValues,
    IdentityResolution,
    ResolutionMethod,
    ResolutionStatus,
    ResolvedIdentity,
    UserIdentity,
    parse_timestamp,
)
from privacyguard.planning.planner import StepPlanner
from privacyguard.policy.engine import PolicyEngine
from privacyguard.policy.rules import load_policy_rules
from privacyguard.state.engine import StateEngine
from privacyguard.models import parse_timestamp as _parse

from .connector import SmartShopConnector
from .adapter import customer_observation, activity_from_row

from privacyguard.evidence.models import (
    EvidenceFormat,
    EvidenceLocation,
    EvidenceObservation,
    EvidenceProvenance,
    ObservedState,
)
from .seed import seeded_customers


def _customer(customer_id: str) -> dict[str, Any]:
    for customer in seeded_customers():
        if customer["customer_id"] == customer_id:
            return customer
    raise KeyError(customer_id)


def _ts(value: Any) -> datetime:
    from datetime import datetime as _dt

    if isinstance(value, _dt):
        return value
    return parse_timestamp(str(value))


def _primary_email(rows: list[dict[str, Any]]) -> str:
    primary = [row for row in rows if row.get("is_primary")]
    if not primary:
        primary = rows
    if not primary:
        raise ValueError("customer has no email record")
    return str(primary[0]["email_normalized"])


def _historical_emails(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    emails: list[str] = []
    for row in rows:
        if row.get("is_primary"):
            continue
        value = row.get("email_normalized")
        if value is not None:
            emails.append(str(value))
    return tuple(dict.fromkeys(emails))


def audit_smartshop_request(request_id: str, *, rules_path=None, connector=None) -> AuditResult:
    if rules_path is None:
        rules_path = Path(__file__).resolve().parent / "deletion_rules.csv"
    if connector is None:
        connector = SmartShopConnector(
            host=os.environ["SMARTSHOP_PG_HOST"],
            port=os.environ.get("SMARTSHOP_PG_PORT", "5432"),
            user=os.environ["SMARTSHOP_PG_USER"],
            password=os.environ["SMARTSHOP_PG_PASSWORD"],
            database=os.environ.get("SMARTSHOP_PG_DATABASE", "smartshop_test"),
        )
    req = connector.fetch_deletion_request(request_id)
    if not req:
        raise ValueError(f"unknown request_id {request_id}")
    customer_id = req["customer_id"]
    customer = connector.fetch_customer(customer_id)
    if not customer:
        customer = _customer(customer_id)

    related = connector.fetch_related(customer_id, request_id)
    customer_emails = related.get("customer_emails", [])

    observations = [customer_observation(customer)]
    # Email relationship observations
    for email_row in customer_emails:
        moment = _ts(email_row["recorded_at"])
        obs = EvidenceObservation(
            observation_id=f"smartshop:customer_emails:{email_row['email_id']}",
            file_id="smartshop",
            file_path="smartshop://customer_emails",
            captured_at=moment,
            observed_at=moment,
            format=EvidenceFormat.SQL,
            system_id="identity_service",
            resource_id=f"secondary_identifier_{email_row['email_id']}",
            data_category="SECONDARY_IDENTIFIER",
            observed_state=ObservedState.PRESENT,
            emails=(str(email_row["email_normalized"]),),
            attributes={"origin": "smartshop.customer_emails", "customer_id": customer_id, "is_primary": bool(email_row.get("is_primary"))},
            record=dict(email_row),
            provenance=EvidenceProvenance(
                file_id="smartshop",
                file_path="smartshop://customer_emails",
                captured_at=moment,
                source_format=EvidenceFormat.SQL,
                location=EvidenceLocation(table="customer_emails"),
            ),
            confidence=0.9,
        )
        observations.append(obs)

    for ticket in related.get("support_tickets", []):
        attrs = {
            "requester_name": ticket.get("requester_name"),
            "requester_email": ticket.get("requester_email"),
            "requester_phone": ticket.get("requester_phone"),
            "message_excerpt": ticket.get("subject"),
        }
        obs = EvidenceObservation(
            observation_id=f"smartshop:support_tickets:{ticket['ticket_id']}",
            file_id="smartshop",
            file_path="smartshop://support_tickets",
            captured_at=_ts(ticket["created_at"]),
            observed_at=_ts(ticket["created_at"]),
            format=EvidenceFormat.SQL,
            system_id="support_platform",
            resource_id=f"support_{ticket['ticket_id']}",
            data_category="SUPPORT_MESSAGE",
            observed_state=ObservedState.PRESENT,
            user_ids=(str(customer_id),),
            attributes=attrs,
            record=dict(ticket),
            provenance=EvidenceProvenance(
                file_id="smartshop",
                file_path="smartshop://support_tickets",
                captured_at=_ts(ticket["created_at"]),
                source_format=EvidenceFormat.SQL,
                location=EvidenceLocation(table="support_tickets"),
            ),
            confidence=0.9,
        )
        observations.append(obs)

    for contact in related.get("marketing_contacts", []):
        obs = EvidenceObservation(
            observation_id=f"smartshop:marketing_contacts:{contact['marketing_id']}",
            file_id="smartshop",
            file_path="smartshop://marketing_contacts",
            captured_at=_ts(contact["created_at"]),
            observed_at=_ts(contact["created_at"]),
            format=EvidenceFormat.SQL,
            system_id="marketing_platform",
            resource_id=f"marketing_{contact['marketing_id']}",
            data_category="MARKETING_PROFILE",
            observed_state=ObservedState.PRESENT,
            user_ids=(str(customer_id),),
            emails=(str(contact["email"]),),
            attributes={"origin": "smartshop.marketing_contacts", "customer_id": customer_id},
            record=dict(contact),
            provenance=EvidenceProvenance(
                file_id="smartshop",
                file_path="smartshop://marketing_contacts",
                captured_at=_ts(contact["created_at"]),
                source_format=EvidenceFormat.SQL,
                location=EvidenceLocation(table="marketing_contacts"),
            ),
            confidence=0.9,
        )
        observations.append(obs)

    for backup in related.get("backup_inventory", []):
        obs = EvidenceObservation(
            observation_id=f"smartshop:backup_inventory:{backup['backup_id']}",
            file_id="smartshop",
            file_path="smartshop://backup_inventory",
            captured_at=_ts(backup["captured_at"]),
            observed_at=_ts(backup["captured_at"]),
            format=EvidenceFormat.SQL,
            system_id="backup_service",
            resource_id=f"backup_{backup['backup_id']}",
            data_category="BACKUP_ARCHIVE",
            observed_state=ObservedState.ACTIVE,
            user_ids=(),
            attributes={
                "origin": "smartshop.backup_inventory",
                "completeness_scope": backup.get("completeness_scope"),
                "restore_allowed": str(backup.get("completeness_scope")) != "COMPLETE_COLLECTION",
            },
            record=dict(backup),
            provenance=EvidenceProvenance(
                file_id="smartshop",
                file_path="smartshop://backup_inventory",
                captured_at=_ts(backup["captured_at"]),
                source_format=EvidenceFormat.SQL,
                location=EvidenceLocation(table="backup_inventory"),
            ),
            confidence=0.9,
        )
        observations.append(obs)

    activity = [activity_from_row(r) for r in related.get("deletion_activity", [])]
    for row in related.get("sync_events", []):
        if not isinstance(row, dict):
            continue
        activity.append(
            activity_from_row(
                {
                    "activity_id": row.get("sync_id"),
                    "event_time": row.get("event_time"),
                    "event_type": "SYNC_RECORD",
                    "source_system": row.get("source_system", "smartshop"),
                    "target_system": row.get("target_system", "smartshop"),
                    "resource_id": row.get("resource_id"),
                    "reported_result": row.get("reported_result", "SUCCESS"),
                    "details": f"sync {row.get('resource_type')}",
                }
            )
        )

    primary_email = _primary_email(customer_emails)
    hist_emails = _historical_emails(customer_emails)
    hist_values = HistoricalValues(emails=hist_emails)
    current = UserIdentity(
        user_id=customer_id,
        name=str(customer["full_name"]),
        email=primary_email,
        phone="+1 555 000 0000",
        email_hash="a" * 64,
        updated_at=str(customer["created_at"]),
    )
    identity = ResolvedIdentity(
        user_id=customer_id,
        current=current,
        historical=hist_values,
        all_emails=tuple(dict.fromkeys((primary_email,) + hist_emails)),
        all_phones=(current.phone,),
        all_email_hashes=(current.email_hash,),
        provenance=(),
        warnings=(),
    )
    resolution = IdentityResolution(
        status=ResolutionStatus.RESOLVED,
        identifier=primary_email,
        normalized_identifier=primary_email,
        kind="email",
        method=ResolutionMethod.CURRENT_EMAIL,
        matched_value=primary_email,
        user_id=customer_id,
        identity=identity,
    )

    audit_at = parse_timestamp(str(req["audit_at"]))
    request_obj = DeletionRequest.model_construct(
        case_id=request_id,
        email=primary_email,
        requested_at=parse_timestamp(str(req["requested_at"])),
        reported_status=req["reported_status"],
        reported_at=parse_timestamp(str(req["reported_at"])),
        audit_at=parse_timestamp(str(req["audit_at"])),
        request_text=req["request_text"],
    )
    wf_start, wf_end = _workflow_window(request_obj)

    evidence_index = EvidenceIndex(observations)
    activity_index = ActivityIndex(activity)
    linker = ResourceLinker(evidence_index, activity_index)
    link = linker.link(identity, audit_at=audit_at, workflow_start=wf_start, workflow_end=wf_end)

    states = StateEngine(evidence_index, activity_index).reconstruct(link.linked, audit_at)
    states, proofs = (states, ())

    context = AuditContext(
        case_id=request_id,
        audit_at=audit_at,
        request=request_obj,
        resolution=resolution,
        identity=identity,
        linked_resources=link.linked,
        account_candidates=link.candidates,
        absence_proofs=proofs,
        unresolved_resources=link.unresolved,
        candidate_activity_resources=(),
        states=states,
        uncertainties=(),
        relevant_observations=observations,
        relevant_activity=activity,
    )

    rules = load_policy_rules(rules_path)
    return AuditDecisionEngine(PolicyEngine(rules), StepPlanner()).audit(context)
