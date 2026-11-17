from __future__ import annotations

import os
from pathlib import Path

from .db import run_psql, SCHEMA_PATH
from .seed import seed_sql


def _run(sql: str) -> str:
    result = run_psql(sql=sql)
    if result.returncode != 0:
        raise RuntimeError(f"psql failed: {result.stderr.strip() or result.stdout.strip()}")
    return (result.stdout + result.stderr).strip()


def preflight() -> dict[str, object]:
    """Read-only inventory of the configured smartshop_test database."""
    probe = _run("SELECT current_database();")
    if "smartshop_test" not in probe.split():
        raise RuntimeError(
            "Refusing to continue: target database is not smartshop_test "
            f"(probe output: {probe!r})."
        )
    try:
        tables = int(_run(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='smartshop';"
        ).split()[-1])
    except (ValueError, IndexError):
        tables = 0
    return {"database": "smartshop_test", "smartshop_tables": tables}


def setup_database(*, allow_reset: bool = False) -> dict[str, str]:
    """Create schema and seed data in the explicitly configured test database."""
    probe = _run("SELECT current_database();")
    if "smartshop_test" not in probe.split():
        raise RuntimeError(
            "Refusing to continue: target database is not smartshop_test "
            f"(probe output: {probe!r})."
        )

    if allow_reset is False:
        try:
            existing = int(_run("SELECT count(*) FROM smartshop.customers;").split()[-1])
        except Exception:
            existing = 0
        if existing:
            raise RuntimeError(
                "SmartShop tables already contain data. Re-run with allow_reset=True "
                "(SMARTSHOP_ALLOW_RESET=1) only after confirming a destructive reset."
            )

    schema_result = run_psql(file=SCHEMA_PATH)
    if schema_result.returncode != 0:
        raise RuntimeError(
            "Schema creation failed: "
            + (schema_result.stderr.strip() or schema_result.stdout.strip())
        )

    allow_reset = allow_reset or os.environ.get("SMARTSHOP_ALLOW_RESET") == "1"
    seed_file = Path(__file__).resolve().parent / "seed.sql"
    seed_file.write_text(seed_sql(allow_reset=allow_reset), encoding="utf-8")
    seed_result = run_psql(file=seed_file)
    if seed_result.returncode != 0:
        # Rollback is automatic because seed.sql is wrapped in BEGIN/COMMIT and
        # psql stops at the first error.
        raise RuntimeError(
            "Seeding failed, transaction rolled back: "
            + (seed_result.stderr.strip() or seed_result.stdout.strip())
        )

    return {
        "database": "smartshop_test",
        "schema": _run("SELECT count(*) FROM information_schema.tables WHERE table_schema='smartshop';"),
        "customers": _run("SELECT count(*) FROM smartshop.customers;"),
        "support_tickets": _run("SELECT count(*) FROM smartshop.support_tickets;"),
        "backup_inventory": _run("SELECT count(*) FROM smartshop.backup_inventory;"),
    }


if __name__ == "__main__":
    print(setup_database())
