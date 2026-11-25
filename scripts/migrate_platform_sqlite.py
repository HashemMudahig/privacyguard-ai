"""Copy legacy platform rows from SQLite (read-only) into PostgreSQL once."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import inspect

from privacyguard.platform.database import PlatformDatabase, resolve_database_url
from privacyguard.platform.models import AuditRequest, AuditRun, AuditTask, EvidenceRecord, Workspace

TABLES = (
    Workspace.__table__,
    AuditRequest.__table__,
    AuditRun.__table__,
    EvidenceRecord.__table__,
    AuditTask.__table__,
)
DATETIME_COLUMNS = {"audit_at", "created_at", "completed_at"}


def _parse_datetime(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _read_source(source: Path) -> dict[str, list[dict[str, Any]]]:
    if not source.is_file():
        raise FileNotFoundError(f"SQLite source does not exist: {source}")
    uri = f"{source.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        rows_by_table: dict[str, list[dict[str, Any]]] = {}
        for table in TABLES:
            columns = [column.name for column in table.columns]
            source_columns = {
                row[1]
                for row in connection.execute(f"PRAGMA table_info({table.name})")
            }
            missing_required = [
                column.name
                for column in table.columns
                if column.name not in source_columns
                and not column.nullable
                and column.default is None
                and column.server_default is None
            ]
            if missing_required:
                raise RuntimeError(
                    f"Legacy table {table.name} is missing required columns: "
                    + ", ".join(missing_required)
                )
            selected_columns = [name for name in columns if name in source_columns]
            query = (
                f"SELECT {', '.join(selected_columns)} FROM {table.name}"
            )  # trusted ORM names
            rows = []
            for source_row in connection.execute(query):
                row = dict(source_row)
                for column in table.columns:
                    if column.name not in row:
                        row[column.name] = None
                for name in DATETIME_COLUMNS.intersection(row):
                    if row[name] is not None:
                        row[name] = _parse_datetime(row[name])
                rows.append(row)
            rows_by_table[table.name] = rows
        return rows_by_table
    finally:
        connection.close()


def migrate(source: Path, target_url: str) -> dict[str, int]:
    source_rows = _read_source(source)
    platform_db = PlatformDatabase(target_url)
    required = {table.name for table in TABLES}
    try:
        with platform_db.engine.begin() as connection:
            missing = required.difference(inspect(connection).get_table_names())
            if missing:
                raise RuntimeError(
                    "Target schema is not migrated; missing tables: " + ", ".join(sorted(missing))
                )
            occupied = {
                table.name: connection.execute(table.select().limit(1)).first() is not None
                for table in TABLES
            }
            if any(occupied.values()):
                names = ", ".join(name for name, has_rows in occupied.items() if has_rows)
                raise RuntimeError(f"Target is not empty; refusing to merge rows into: {names}")
            for table in TABLES:
                rows = source_rows[table.name]
                if rows:
                    connection.execute(table.insert(), rows)
        return {name: len(rows) for name, rows in source_rows.items()}
    finally:
        platform_db.engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("privacyguard_platform.db"),
        help="legacy SQLite file, always opened in read-only mode",
    )
    args = parser.parse_args()
    counts = migrate(args.source, resolve_database_url())
    print("Migration committed: " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
