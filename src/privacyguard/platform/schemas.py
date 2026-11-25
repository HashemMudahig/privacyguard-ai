from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class WorkspaceCreate(BaseModel):
    id: str
    name: str


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    created_at: datetime


class AuditRequestCreate(BaseModel):
    request_id: str
    email: str
    audit_at: datetime
    request_text: str


class AuditRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    workspace_id: str
    request_id: str
    email: str
    audit_at: datetime
    created_at: datetime


class AuditRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    audit_request_id: str
    status: str
    step_count: int
    created_at: datetime
    completed_at: datetime | None = None
    verification_status: str | None = None


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    audit_run_id: str
    source: str
    resource_id: str
    observed_state: str
    created_at: datetime
