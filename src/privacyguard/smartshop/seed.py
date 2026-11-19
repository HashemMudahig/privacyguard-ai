from __future__ import annotations

import random
from dataclasses import dataclass


FIXED_SEED = 0xA1B2C3D4


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    customer_id: str
    has_historical_email: bool
    deletion_result: str
    retained_invoice: bool
    partial_backup: bool
    reappearance_after_restore: bool


SCENARIOS: tuple[ScenarioSpec, ...] = (
    ScenarioSpec("fully_verified", "CUST-1001", False, "COMPLETE", False, False, False),
    ScenarioSpec("partial_support", "CUST-1002", False, "INCOMPLETE", False, False, False),
    ScenarioSpec("retained_invoice", "CUST-1003", False, "COMPLETE", True, False, False),
    ScenarioSpec("partial_backup", "CUST-1004", False, "INCOMPLETE", False, True, False),
    ScenarioSpec("historical_email", "CUST-1005", True, "COMPLETE", False, False, False),
    ScenarioSpec("restore_reappearance", "CUST-1006", False, "INCOMPLETE", False, False, True),
)


_FICTIONAL_FIRST = ("Ava", "Noah", "Luna", "Miles", "Iris", "Theo")
_FICTIONAL_LAST = ("Carter", "Bennett", "Reed", "Hayes", "Frost", "Quinn")
_DOMAINS = ("example.com", "example.net", "example.org")


def seeded_customers(seed: int = FIXED_SEED) -> list[dict[str, object]]:
    rng = random.Random(seed)
    customers: list[dict[str, object]] = []
    for index, spec in enumerate(SCENARIOS):
        rng.choice(_FICTIONAL_FIRST)
        rng.choice(_FICTIONAL_LAST)
        first = rng.choice(_FICTIONAL_FIRST)
        last = rng.choice(_FICTIONAL_LAST)
        domain = rng.choice(_DOMAINS)
        email = f"{first.lower()}.{last.lower()}.{spec.customer_id.lower()}@{domain}"
        historical = (
            f"old.{first.lower()}.{spec.customer_id.lower()}@{domain}"
            if spec.has_historical_email
            else None
        )
        customer = {
            "customer_id": spec.customer_id,
            "full_name": f"{first} {last}",
            "created_at": f"2026-01-{10 + index:02d}T09:00:00Z",
            "current_status": "ACTIVE" if spec.deletion_result == "COMPLETE" else "DELETED",
            "primary_email": email,
            "historical_email": historical,
            "scenario": spec.scenario_id,
        }
        customers.append(customer)
    return customers


def scenario_specs() -> list[ScenarioSpec]:
    return list(SCENARIOS)


def _sql_escape(value: str) -> str:
    return value.replace("'", "''")


def seed_sql(*, allow_reset: bool = False) -> str:
    """Return deterministic SQL that populates SmartShop.

    By default no TRUNCATE is generated and INSERTs are idempotent.
    """
    customers = seeded_customers()
    statements: list[str] = []
    if allow_reset:
        statements.append(
            "TRUNCATE smartshop.sync_events, smartshop.backup_inventory, smartshop.deletion_activity, "
            "smartshop.deletion_requests, smartshop.marketing_contacts, smartshop.support_attachments, "
            "smartshop.support_tickets, smartshop.invoices, smartshop.orders, smartshop.customer_emails, "
            "smartshop.customers RESTART IDENTITY;"
        )

    customer_ids: list[str] = []
    for customer in customers:
        customer_ids.append(str(customer["customer_id"]))
        statements.append(
            "INSERT INTO smartshop.customers (customer_id, full_name, created_at, current_status) "
            "VALUES ({id}, {name}, {created}::timestamptz, {status});".format(
                id="'" + _sql_escape(str(customer["customer_id"])) + "'",
                name="'" + _sql_escape(str(customer["full_name"])) + "'",
                created="'" + _sql_escape(str(customer["created_at"])) + "'",
                status="'" + _sql_escape(str(customer["current_status"])) + "'",
            )
        )
        statements.append(
            "INSERT INTO smartshop.customer_emails (email_id, customer_id, email_normalized, is_primary, recorded_at, valid_until) "
            "VALUES ({eid}, {cid}, {email}, TRUE, {recorded}::timestamptz, NULL);".format(
                eid="'" + _sql_escape(str(customer["customer_id"])) + "_email'",
                cid="'" + _sql_escape(str(customer["customer_id"])) + "'",
                email="'" + _sql_escape(str(customer["primary_email"])) + "'",
                recorded="'" + _sql_escape(str(customer["created_at"])) + "'",
            )
        )
        if customer["historical_email"]:
            statements.append(
                "INSERT INTO smartshop.customer_emails (email_id, customer_id, email_normalized, is_primary, recorded_at, valid_until) "
                "VALUES ({eid}, {cid}, {email}, FALSE, {recorded}::timestamptz, {valid}::timestamptz);".format(
                    eid="'" + _sql_escape(str(customer["customer_id"])) + "_hist_email'",
                    cid="'" + _sql_escape(str(customer["customer_id"])) + "'",
                    email="'" + _sql_escape(str(customer["historical_email"])) + "'",
                    recorded="'" + _sql_escape(str(customer["created_at"])) + "'",
                    valid="'" + _sql_escape(str(customer["created_at"])) + "'",
                )
            )

    # Orders + invoices, one order per customer for deterministic coverage.
    for index, cid in enumerate(customer_ids, start=1):
        order_id = f"ORD-{index:04d}"
        statements.append(
            "INSERT INTO smartshop.orders (order_id, customer_id, status, total_amount, created_at) "
            "VALUES ({oid}, {cid}, 'PAID', 100.00, '2026-02-{day:02d}T10:00:00Z'::timestamptz);".format(
                oid="'" + order_id + "'",
                cid="'" + _sql_escape(cid) + "'",
                day=10 + index,
            )
        )
        statements.append(
            "INSERT INTO smartshop.invoices (invoice_id, order_id, retention_reason, issued_at) "
            "VALUES ({iid}, {oid}, {reason}, '2026-02-{day:02d}T10:00:00Z'::timestamptz);".format(
                iid="'" + f"INV-{index:04d}" + "'",
                oid="'" + order_id + "'",
                reason="'Policy retention'" if cid == "CUST-1003" else "'Standard retention'",
                day=10 + index,
            )
        )

    # Support tickets and attachments.
    for index, cid in enumerate(customer_ids, start=1):
        ticket_id = f"TICKET-{index:04d}"
        redacted = cid in {"CUST-1001", "CUST-1003", "CUST-1005"}
        statements.append(
            "INSERT INTO smartshop.support_tickets (ticket_id, customer_id, subject, status, created_at, "
            "requester_name, requester_email, requester_phone) VALUES ({tid}, {cid}, {subj}, 'CLOSED', "
            "'2026-02-{day:02d}T11:00:00Z'::timestamptz, {name}, {email}, {phone});".format(
                tid="'" + ticket_id + "'",
                cid="'" + _sql_escape(cid) + "'",
                subj="'" + _sql_escape(f"Order support for {cid}") + "'",
                day=10 + index,
                name="NULL" if redacted else "'Test User'",
                email="NULL" if redacted else "'test@example.com'",
                phone="NULL" if redacted else "'+1 555 000 0000'",
            )
        )
        statements.append(
            "INSERT INTO smartshop.support_attachments (attachment_id, ticket_id, file_ref, pii_redacted, uploaded_at) "
            "VALUES ({aid}, {tid}, {ref}, {red}, '2026-02-{day:02d}T11:30:00Z'::timestamptz);".format(
                aid="'" + f"ATT-{index:04d}" + "'",
                tid="'" + ticket_id + "'",
                ref="'" + _sql_escape(f"attachment_{index}.pdf") + "'",
                red="TRUE" if redacted else "FALSE",
                day=10 + index,
            )
        )

    # Marketing contacts (partial remainder for some scenarios).
    for index, cid in enumerate(customer_ids, start=1):
        if cid in {"CUST-1002", "CUST-1004"}:
            statements.append(
                "INSERT INTO smartshop.marketing_contacts (marketing_id, customer_id, email, campaign, status, created_at) "
                "VALUES ({mid}, {cid}, {email}, 'WELCOME', 'ACTIVE', '2026-02-{day:02d}T12:00:00Z'::timestamptz);".format(
                    mid="'" + f"MKT-{index:04d}" + "'",
                    cid="'" + _sql_escape(cid) + "'",
                    email="'" + _sql_escape(str(next(c for c in customers if c["customer_id"] == cid)["primary_email"])) + "'",
                    day=10 + index,
                )
            )

    # Deletion requests + activity, sync, and backup events for each customer.
    for index, cid in enumerate(customer_ids, start=1):
        request_id = f"REQ-{index:04d}"
        statements.append(
            "INSERT INTO smartshop.deletion_requests (request_id, customer_id, requested_at, reported_status, reported_at, audit_at, request_text) "
            "VALUES ({rid}, {cid}, '2026-03-01T00:00:00Z'::timestamptz, {reported}, '2026-03-02T00:00:00Z'::timestamptz, '2026-03-10T00:00:00Z'::timestamptz, 'Delete my account and personal data.');".format(
                rid="'" + request_id + "'",
                cid="'" + _sql_escape(cid) + "'",
                reported="'COMPLETE'" if cid in {"CUST-1001", "CUST-1003", "CUST-1005"} else "'PARTIALLY_COMPLETE'",
            )
        )
        statements.append(
            "INSERT INTO smartshop.deletion_activity (activity_id, request_id, resource_type, resource_id, event_time, event_type, reported_result) "
            "VALUES ({aid}, {rid}, 'account', {rid2}, '2026-03-03T00:00:00Z'::timestamptz, 'DELETE_RECORD', 'SUCCESS');".format(
                aid="'" + f"ACT-{index:04d}" + "'",
                rid="'" + request_id + "'",
                rid2="'" + _sql_escape(cid) + "'",
            )
        )
        statements.append(
            "INSERT INTO smartshop.backup_inventory (backup_id, system_name, captured_at, resource_table, record_count, completeness_scope) "
            "VALUES ({bid}, 'orders_backup', '2026-03-05T00:00:00Z'::timestamptz, 'orders', {count}, {scope});".format(
                bid="'" + f"BKP-{index:04d}" + "'",
                count=1 if cid == "CUST-1004" else 0,
                scope="'PARTIAL_INVENTORY'" if cid == "CUST-1004" else "'COMPLETE_COLLECTION'",
            )
        )
        if cid == "CUST-1006":
            statements.append(
                "INSERT INTO smartshop.sync_events (sync_id, event_time, source_system, target_system, resource_type, resource_id, reported_result) "
                "VALUES ('SYNC-0001', '2026-03-09T00:00:00Z'::timestamptz, 'warehouse', 'search_service', 'account', 'CUST-1006', 'SUCCESS');"
            )

    if not allow_reset:
        transformed = []
        for statement in statements:
            if statement.startswith("INSERT"):
                statement = statement.replace(");", ") ON CONFLICT DO NOTHING;")
            transformed.append(statement)
        statements = transformed

    return "BEGIN;\n" + "\n".join(statements) + "\nCOMMIT;\n"
