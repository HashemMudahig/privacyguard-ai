from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    audit_requests: Mapped[list["AuditRequest"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AuditRequest(Base):
    __tablename__ = "audit_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    audit_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "request_id", name="uq_workspace_request"),
        Index("ix_audit_requests_workspace_created_at", "workspace_id", "created_at"),
    )

    workspace: Mapped[Workspace] = relationship(back_populates="audit_requests")
    runs: Mapped[list["AuditRun"]] = relationship(
        back_populates="audit_request",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AuditRun(Base):
    __tablename__ = "audit_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_request_id: Mapped[str] = mapped_column(ForeignKey("audit_requests.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        Index("ix_audit_runs_request_created_at", "audit_request_id", "created_at"),
    )

    audit_request: Mapped[AuditRequest] = relationship(back_populates="runs")
    evidence_records: Mapped[list["EvidenceRecord"]] = relationship(
        back_populates="audit_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    tasks: Mapped[list["AuditTask"]] = relationship(
        back_populates="audit_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class EvidenceRecord(Base):
    __tablename__ = "evidence_records"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    audit_run_id: Mapped[str] = mapped_column(ForeignKey("audit_runs.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_evidence_records_audit_run_id", "audit_run_id"),)

    audit_run: Mapped[AuditRun] = relationship(back_populates="evidence_records")


class AuditTask(Base):
    __tablename__ = "audit_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_run_id: Mapped[str] = mapped_column(ForeignKey("audit_runs.id", ondelete="CASCADE"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_audit_tasks_audit_run_id", "audit_run_id"),)

    audit_run: Mapped[AuditRun] = relationship(back_populates="tasks")
