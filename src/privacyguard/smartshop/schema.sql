CREATE SCHEMA IF NOT EXISTS smartshop;

CREATE TABLE IF NOT EXISTS smartshop.customers (
    customer_id          text PRIMARY KEY,
    full_name            text NOT NULL,
    created_at           timestamptz NOT NULL,
    current_status       text NOT NULL
);

CREATE TABLE IF NOT EXISTS smartshop.customer_emails (
    email_id             text PRIMARY KEY,
    customer_id          text NOT NULL REFERENCES smartshop.customers(customer_id) ON DELETE CASCADE,
    email_normalized     text NOT NULL,
    is_primary           boolean NOT NULL DEFAULT FALSE,
    recorded_at          timestamptz NOT NULL,
    valid_until          timestamptz NULL
);

CREATE TABLE IF NOT EXISTS smartshop.orders (
    order_id             text PRIMARY KEY,
    customer_id          text NOT NULL REFERENCES smartshop.customers(customer_id) ON DELETE CASCADE,
    status               text NOT NULL,
    total_amount         numeric(10, 2) NOT NULL,
    created_at           timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS smartshop.invoices (
    invoice_id           text PRIMARY KEY,
    order_id             text NOT NULL REFERENCES smartshop.orders(order_id) ON DELETE CASCADE,
    retention_reason     text NOT NULL,
    issued_at            timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS smartshop.support_tickets (
    ticket_id            text PRIMARY KEY,
    customer_id          text NOT NULL REFERENCES smartshop.customers(customer_id) ON DELETE CASCADE,
    subject              text NOT NULL,
    status               text NOT NULL,
    created_at           timestamptz NOT NULL,
    requester_name       text,
    requester_email      text,
    requester_phone      text
);

CREATE TABLE IF NOT EXISTS smartshop.support_attachments (
    attachment_id        text PRIMARY KEY,
    ticket_id            text NOT NULL REFERENCES smartshop.support_tickets(ticket_id) ON DELETE CASCADE,
    file_ref             text NOT NULL,
    pii_redacted         boolean NOT NULL DEFAULT FALSE,
    uploaded_at          timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS smartshop.marketing_contacts (
    marketing_id         text PRIMARY KEY,
    customer_id          text,
    email                text NOT NULL,
    campaign             text NOT NULL,
    status               text NOT NULL,
    created_at           timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS smartshop.deletion_requests (
    request_id           text PRIMARY KEY,
    customer_id          text NOT NULL REFERENCES smartshop.customers(customer_id) ON DELETE CASCADE,
    requested_at         timestamptz NOT NULL,
    reported_status      text NOT NULL,
    reported_at          timestamptz NOT NULL,
    audit_at             timestamptz NOT NULL,
    request_text         text NOT NULL
);

CREATE TABLE IF NOT EXISTS smartshop.deletion_activity (
    activity_id          text PRIMARY KEY,
    request_id           text NOT NULL REFERENCES smartshop.deletion_requests(request_id) ON DELETE CASCADE,
    resource_type        text NOT NULL,
    resource_id          text NOT NULL,
    event_time           timestamptz NOT NULL,
    event_type           text NOT NULL,
    reported_result      text NOT NULL
);

CREATE TABLE IF NOT EXISTS smartshop.backup_inventory (
    backup_id            text PRIMARY KEY,
    system_name          text NOT NULL,
    captured_at          timestamptz NOT NULL,
    resource_table       text NOT NULL,
    record_count         integer NOT NULL CHECK (record_count >= 0),
    completeness_scope   text NOT NULL
);

CREATE TABLE IF NOT EXISTS smartshop.sync_events (
    sync_id              text PRIMARY KEY,
    event_time           timestamptz NOT NULL,
    source_system        text NOT NULL,
    target_system        text NOT NULL,
    resource_type        text NOT NULL,
    resource_id          text NOT NULL,
    reported_result      text NOT NULL
);

CREATE INDEX IF NOT EXISTS smartshop_customers_created_at_idx ON smartshop.customers(created_at);
CREATE INDEX IF NOT EXISTS smartshop_customer_emails_customer_idx ON smartshop.customer_emails(customer_id);
CREATE INDEX IF NOT EXISTS smartshop_orders_customer_idx ON smartshop.orders(customer_id);
CREATE INDEX IF NOT EXISTS smartshop_invoices_order_idx ON smartshop.invoices(order_id);
CREATE INDEX IF NOT EXISTS smartshop_tickets_customer_idx ON smartshop.support_tickets(customer_id);
CREATE INDEX IF NOT EXISTS smartshop_attachments_ticket_idx ON smartshop.support_attachments(ticket_id);
CREATE INDEX IF NOT EXISTS smartshop_marketing_customer_idx ON smartshop.marketing_contacts(customer_id);
CREATE INDEX IF NOT EXISTS smartshop_deletion_requests_customer_idx ON smartshop.deletion_requests(customer_id);
CREATE INDEX IF NOT EXISTS smartshop_deletion_activity_request_idx ON smartshop.deletion_activity(request_id);
CREATE INDEX IF NOT EXISTS smartshop_backup_inventory_captured_idx ON smartshop.backup_inventory(captured_at);
CREATE INDEX IF NOT EXISTS smartshop_sync_events_event_time_idx ON smartshop.sync_events(event_time);
