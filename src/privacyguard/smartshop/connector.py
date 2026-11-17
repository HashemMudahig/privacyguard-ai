from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
from dataclasses import dataclass

import psycopg2
import psycopg2.extras

from .db import settings_from_env

ALLOWED_TABLES = frozenset(
    {
        "customers", "customer_emails", "orders", "invoices", "support_tickets",
        "support_attachments", "marketing_contacts", "deletion_requests",
        "deletion_activity", "backup_inventory", "sync_events",
    }
)
ALLOWED_COLUMNS = frozenset(
    {
        "customer_id", "full_name", "created_at", "current_status",
        "email_id", "email_normalized", "is_primary", "recorded_at", "valid_until",
        "order_id", "status", "total_amount", "invoice_id", "retention_reason",
        "issued_at", "ticket_id", "subject", "requester_name", "requester_email",
        "requester_phone", "attachment_id", "file_ref", "pii_redacted", "uploaded_at",
        "marketing_id", "email", "campaign", "request_id", "requested_at",
        "reported_status", "reported_at", "audit_at", "request_text", "activity_id",
        "resource_type", "resource_id", "event_time", "event_type", "reported_result",
        "backup_id", "system_name", "captured_at", "resource_table", "record_count",
        "completeness_scope", "sync_id", "source_system", "target_system",
        "resource_id",
    }
)


@dataclass(slots=True)
class SmartShopConnector:
    """Read-only PostgreSQL connector for the SmartShop test schema."""

    host: str
    port: str
    user: str
    password: str
    database: str = "smartshop_test"

    def _settings(self) -> dict[str, str]:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
        }

    def _connect(self):
        cfg = self._settings()
        if cfg["database"] != "smartshop_test":
            raise ValueError("connector is pinned to smartshop_test")
        conn = psycopg2.connect(
            host=cfg["host"],
            port=cfg["port"],
            user=cfg["user"],
            password=cfg["password"],
            dbname=cfg["database"],
            connect_timeout=5,
            options="-c default_transaction_read_only=on",
        )
        conn.autocommit = False
        return conn

    @contextmanager
    def transaction(self) -> Iterator[psycopg2.extensions.connection]:
        conn = self._connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def fetch(self, table: str, where_column: str, value: str, limit: int = 100) -> list[dict[str, Any]]:
        if table not in ALLOWED_TABLES:
            raise ValueError(f"table not allowlisted: {table}")
        if where_column not in {"customer_id", "request_id", "ticket_id", "order_id", "resource_id", "resource_table"}:
            raise ValueError(f"filter column not allowed: {where_column}")
        if limit < 1 or limit > 5000:
            raise ValueError("limit out of range")
        query = (
            f"SELECT * FROM smartshop.{table} "
            f"WHERE {where_column} = %s LIMIT %s"
        )
        with self.transaction() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, (value, limit))
                return [dict(row) for row in cur.fetchall()]

    def fetch_deletion_request(self, request_id: str) -> dict[str, Any] | None:
        rows = self.fetch("deletion_requests", "request_id", request_id, limit=1)
        return rows[0] if rows else None

    def fetch_customer(self, customer_id: str) -> dict[str, Any] | None:
        rows = self.fetch("customers", "customer_id", customer_id, limit=1)
        return rows[0] if rows else None

    def fetch_related(self, customer_id: str, request_id: str) -> dict[str, list[dict[str, Any]]]:
        return {
            "customer_emails": self.fetch("customer_emails", "customer_id", customer_id),
            "orders": self.fetch("orders", "customer_id", customer_id),
            "support_tickets": self.fetch("support_tickets", "customer_id", customer_id),
            "marketing_contacts": self.fetch("marketing_contacts", "customer_id", customer_id),
            "deletion_activity": self.fetch("deletion_activity", "request_id", request_id),
            "sync_events": self.fetch("sync_events", "resource_id", customer_id),
            "backup_inventory": self.fetch("backup_inventory", "resource_table", "orders"),
        }
