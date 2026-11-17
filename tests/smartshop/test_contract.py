from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from privacyguard.smartshop import audit as audit_mod


def _rows(request_id: str):
    now = datetime(2026, 3, 3, 0, 0, tzinfo=timezone.utc)
    req = {
        "request_id": request_id,
        "customer_id": "CUST-1001",
        "requested_at": now,
        "reported_status": "COMPLETE",
        "reported_at": now,
        "audit_at": now,
        "request_text": "Delete my account and personal data.",
    }
    customer = {
        "customer_id": "CUST-1001",
        "full_name": "Ava Carter",
        "created_at": now,
    }
    emails = [
        {
            "email_id": "CUST-1001_email",
            "customer_id": "CUST-1001",
            "email_normalized": "ava.carter.cust-1001@example.com",
            "is_primary": True,
            "recorded_at": now,
            "valid_until": None,
        }
    ]
    tickets = [
        {
            "ticket_id": "TICKET-0001",
            "customer_id": "CUST-1001",
            "subject": "Order support",
            "status": "CLOSED",
            "created_at": now,
            "requester_name": None,
            "requester_email": None,
            "requester_phone": None,
        }
    ]
    activity = [
        {
            "activity_id": "ACT-0001",
            "request_id": request_id,
            "resource_type": "account",
            "resource_id": "CUST-1001",
            "event_time": now,
            "event_type": "DELETE_RECORD",
            "reported_result": "SUCCESS",
        }
    ]
    return req, customer, emails, tickets, activity


class FakeConnector:
    def __init__(self, request_id: str):
        r, c, e, t, a = _rows(request_id)
        self.request = r
        self.customer = c
        self.emails = e
        self.tickets = t
        self.activity = a

    def fetch_deletion_request(self, _request_id):
        return dict(self.request)

    def fetch_customer(self, _customer_id):
        return dict(self.customer)

    def fetch_related(self, _customer_id, _request_id):
        return {
            "customer_emails": [dict(x) for x in self.emails],
            "orders": [],
            "support_tickets": [dict(x) for x in self.tickets],
            "marketing_contacts": [],
            "deletion_activity": [dict(x) for x in self.activity],
            "sync_events": [],
            "backup_inventory": [],
        }


def test_audit_smartshop_accepts_req_style_request_id(monkeypatch, tmp_path) -> None:
    request_id = "REQ-0001"
    fake = FakeConnector(request_id)
    monkeypatch.setattr(audit_mod, "SmartShopConnector", lambda *a, **k: fake)

    rules = tmp_path / "rules.csv"
    rules.write_text(
        "rule_id,data_category,condition,required_action\n"
        "rule_01,USER_PROFILE,Always,DELETE\n"
        "rule_05,SUPPORT_MESSAGE,\"x\",REDACT\n",
        encoding="utf-8",
    )

    result = audit_mod.audit_smartshop_request(request_id, rules_path=rules, connector=fake)
    assert result.case_id == request_id
    assert result.case_id.startswith("REQ-")
    assert result.deletion_status is not None


def test_audit_smartshop_preserves_request_id_in_context(monkeypatch, tmp_path) -> None:
    request_id = "REQUEST-ABC-99"
    fake = FakeConnector(request_id)
    fake.request["request_id"] = request_id
    monkeypatch.setattr(audit_mod, "SmartShopConnector", lambda *a, **k: fake)

    rules = tmp_path / "rules.csv"
    rules.write_text(
        "rule_id,data_category,condition,required_action\n"
        "rule_01,USER_PROFILE,Always,DELETE\n",
        encoding="utf-8",
    )

    result = audit_mod.audit_smartshop_request(request_id, rules_path=rules, connector=fake)
    assert result.case_id == request_id
    assert result.policy.case_id == request_id
