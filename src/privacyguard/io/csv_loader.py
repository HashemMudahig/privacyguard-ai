"""Strict CSV loading with header validation and row-level errors."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..activity.models import SystemActivity
from ..errors import DatasetError
from ..models import AuditEvent, DeletionRequest, UserIdentity
from .types import DatasetFile, LoadedRow

T = TypeVar("T", bound=BaseModel)

REQUEST_HEADERS = (
    "case_id",
    "email",
    "requested_at",
    "reported_status",
    "reported_at",
    "audit_at",
    "request_text",
)
IDENTITY_HEADERS = ("user_id", "name", "email", "phone", "email_hash", "updated_at")
AUDIT_HEADERS = (
    "audit_id",
    "user_id",
    "event_time",
    "field_name",
    "old_value",
    "new_value",
)
ACTIVITY_HEADERS = (
    "activity_id",
    "event_time",
    "event_type",
    "source_system",
    "target_system",
    "resource_id",
    "reported_result",
    "details",
)


def _load_csv(
    path: Path,
    model: type[T],
    expected_headers: tuple[str, ...],
    display_name: str,
) -> DatasetFile[T]:
    if not path.is_file():
        raise DatasetError(f"Required dataset file is missing: {path}")

    rows: list[LoadedRow[T]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        actual_headers = tuple(reader.fieldnames or ())
        if actual_headers != expected_headers:
            raise DatasetError(
                f"Unexpected header in {path.name}: {actual_headers!r}; "
                f"expected {expected_headers!r}"
            )
        for row_number, raw in enumerate(reader, start=1):
            if None in raw:
                raise DatasetError(
                    f"Row {row_number} in {path.name} has more values than headers"
                )
            try:
                record = model.model_validate(raw)
            except ValidationError as exc:
                raise DatasetError(
                    f"Invalid row {row_number} in {path.name}: {exc}"
                ) from exc
            rows.append(
                LoadedRow(
                    row_number=row_number,
                    record=record,
                    raw={key: (value or "") for key, value in raw.items()},
                )
            )

    return DatasetFile(path=path, display_name=display_name, rows=tuple(rows))


def load_deletion_requests(
    path: str | Path,
    display_name: str | None = None,
) -> DatasetFile[DeletionRequest]:
    """Load an evaluation or sample deletion-request CSV."""
    resolved = Path(path)
    return _load_csv(
        resolved,
        DeletionRequest,
        REQUEST_HEADERS,
        display_name or f"dataset/{resolved.name}",
    )


def load_user_identities(
    path: str | Path,
    display_name: str | None = None,
) -> DatasetFile[UserIdentity]:
    """Load ``user_identities.csv``."""
    resolved = Path(path)
    return _load_csv(
        resolved,
        UserIdentity,
        IDENTITY_HEADERS,
        display_name or f"dataset/{resolved.name}",
    )


def load_audit_events(
    path: str | Path,
    display_name: str | None = None,
) -> DatasetFile[AuditEvent]:
    """Load ``user_audit_log.csv``."""
    resolved = Path(path)
    return _load_csv(
        resolved,
        AuditEvent,
        AUDIT_HEADERS,
        display_name or f"dataset/{resolved.name}",
    )


def load_system_activity(
    path: str | Path,
    display_name: str | None = None,
) -> DatasetFile[SystemActivity]:
    """Load ``system_activity.csv``."""
    resolved = Path(path)
    return _load_csv(
        resolved,
        SystemActivity,
        ACTIVITY_HEADERS,
        display_name or f"dataset/{resolved.name}",
    )
