"""initial platform schema

Revision ID: 2091eaa64392
Revises: 
Create Date: 2026-11-19 13:59:38.274696

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2091eaa64392'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "audit_requests",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("audit_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "request_id", name="uq_workspace_request"),
    )
    op.create_table(
        "audit_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("audit_request_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("step_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_status", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["audit_request_id"], ["audit_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "audit_tasks",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("audit_run_id", sa.String(length=64), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["audit_run_id"], ["audit_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_requests_workspace_created_at",
        "audit_requests",
        ["workspace_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_runs_request_created_at",
        "audit_runs",
        ["audit_request_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_tasks_audit_run_id",
        "audit_tasks",
        ["audit_run_id"],
        unique=False,
    )
    op.create_table(
        "evidence_records",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("audit_run_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=False),
        sa.Column("observed_state", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["audit_run_id"], ["audit_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evidence_records_audit_run_id",
        "evidence_records",
        ["audit_run_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_evidence_records_audit_run_id", table_name="evidence_records")
    op.drop_index("ix_audit_tasks_audit_run_id", table_name="audit_tasks")
    op.drop_index("ix_audit_runs_request_created_at", table_name="audit_runs")
    op.drop_index("ix_audit_requests_workspace_created_at", table_name="audit_requests")
    op.drop_table("evidence_records")
    op.drop_table("audit_tasks")
    op.drop_table("audit_runs")
    op.drop_table("audit_requests")
    op.drop_table("workspaces")
