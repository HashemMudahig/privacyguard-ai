"""SmartShop database connection helpers.

Live PostgreSQL connections are optional. Every helper requires explicit test
environment variables and refuses to operate unless the configured database name
is clearly a test database.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


TEST_DATABASE_PREFIX = "smartshop_"
PSQL = Path(r"C:\Program Files\PostgreSQL\18\bin\psql.exe")
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


class UnsafeSmartShopDatabaseError(ValueError):
    """Raised when a target database is not clearly a SmartShop test database."""


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise UnsafeSmartShopDatabaseError(
            f"Missing required environment variable {name!r} for a SmartShop "
            "database operation."
        )
    return value


def _validate_database_name(name: str) -> None:
    if not name.startswith(TEST_DATABASE_PREFIX):
        raise UnsafeSmartShopDatabaseError(
            f"Refusing to operate on database {name!r}: it must start with "
            f"{TEST_DATABASE_PREFIX!r}."
        )


def _validate_host(host: str) -> None:
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise UnsafeSmartShopDatabaseError(
            "SmartShop may only connect to the local PostgreSQL instance, got "
            f"{host!r}."
        )


def settings_from_env() -> dict[str, str]:
    host = _required_env("SMARTSHOP_PG_HOST")
    _validate_host(host)
    port = os.environ.get("SMARTSHOP_PG_PORT", "5432")
    user = _required_env("SMARTSHOP_PG_USER")
    password = _required_env("SMARTSHOP_PG_PASSWORD")
    database = _required_env("SMARTSHOP_PG_DATABASE")
    _validate_database_name(database)
    if database != "smartshop_test":
        raise UnsafeSmartShopDatabaseError(
            "SmartShop live setup may only target the dedicated smartshop_test database, "
            f"got {database!r}."
        )
    if os.environ.get("SMARTSHOP_TEST_MODE") != "1":
        raise UnsafeSmartShopDatabaseError(
            "SMARTSHOP_TEST_MODE must be set to '1' before any live database "
            "operation."
        )
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": database,
    }


def psql_command(sql: str | None = None, file: Path | None = None) -> list[str]:
    cfg = settings_from_env()
    command = [
        str(PSQL),
        "-X",
        "-w",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        cfg["host"],
        "-p",
        cfg["port"],
        "-U",
        cfg["user"],
        "-d",
        cfg["database"],
    ]
    if file is not None:
        command.extend(["-f", str(file)])
    else:
        command.extend(["-c", sql if sql is not None else ""])
    return command


def run_psql(sql: str | None = None, file: Path | None = None) -> subprocess.CompletedProcess[str]:
    cfg = settings_from_env()
    env = {"PGPASSWORD": cfg["password"]}
    return subprocess.run(
        psql_command(sql=sql, file=file),
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )
