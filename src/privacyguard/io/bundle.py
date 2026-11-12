"""Dataset bundle loading and structural validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..activity.models import SystemActivity
from ..config import Settings
from ..models import AuditEvent, DeletionRequest, UserIdentity
from .csv_loader import (
    load_audit_events,
    load_deletion_requests,
    load_system_activity,
    load_user_identities,
)
from .types import DatasetFile


@dataclass(frozen=True, slots=True)
class DatasetBundle:
    """All identity/activity CSV files loaded from the read-only dataset."""

    dataset_dir: Path
    identities: DatasetFile[UserIdentity]
    audit_events: DatasetFile[AuditEvent]
    sample_requests: DatasetFile[DeletionRequest]
    eval_requests: DatasetFile[DeletionRequest]
    system_activity: DatasetFile[SystemActivity]


def load_dataset(settings: Settings) -> DatasetBundle:
    """Load the four identity-related CSV files.

    This function only reads from ``settings.dataset_dir``. It never writes
    to, renames, or copies any dataset file.
    """
    root = settings.require_dataset()
    return DatasetBundle(
        dataset_dir=root,
        identities=load_user_identities(root / "user_identities.csv"),
        audit_events=load_audit_events(root / "user_audit_log.csv"),
        sample_requests=load_deletion_requests(root / "sample_deletion_requests.csv"),
        eval_requests=load_deletion_requests(root / "deletion_requests.csv"),
        system_activity=load_system_activity(root / "system_activity.csv"),
    )
