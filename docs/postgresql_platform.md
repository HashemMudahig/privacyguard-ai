# PostgreSQL platform persistence

The platform runtime is configured for the dedicated `privacyguard_platform`
PostgreSQL database. The application rejects URLs targeting another PostgreSQL
database. SQLite is supported only through explicit dependency injection for
isolated tests.

## Mandatory safety sequence

1. Configure administrator authentication locally without sharing credentials
   in chat, source, logs, or command-line arguments.
2. Run read-only discovery:

   ```powershell
   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" `
     --dbname postgres `
     --file scripts/discover_platform_postgres.sql
   ```

3. Review whether `privacyguard_platform` or any `privacyguard_platform_*` role
   already exists. Do not assume absence.
4. Obtain explicit approval before any role, database, grant, or migration
   change.
5. Only for a confirmed fresh installation, run
   `scripts/provision_platform_postgres.sql`. It aborts on any target-name
   collision and requires the typed phrase `APPROVE NEW PRIVACYGUARD PLATFORM`.

The current implementation session completed step 2 only as an attempted
read: local PostgreSQL required a password, so catalog discovery could not be
authenticated. No PostgreSQL state was changed.

## Least-privilege role design

- `privacyguard_platform_owner`: `NOLOGIN` object owner.
- `privacyguard_platform_migrator`: login role that may assume only the platform
  owner and is used by Alembic.
- `privacyguard_platform_runtime`: login role with database `CONNECT`, schema
  `USAGE`, and table DML. It cannot create or alter schema objects.

The fresh-install script removes public connect, temporary-table, and public
schema privileges. It never operates on SmartShop or another database.

## Placeholder configuration

Put real values only in process environment variables or an ignored `.env`.
The project itself does not auto-load `.env`.

```text
PRIVACYGUARD_DATABASE_URL=postgresql+psycopg://privacyguard_platform_runtime:<RUNTIME_PASSWORD>@localhost:5432/privacyguard_platform
PRIVACYGUARD_MIGRATION_DATABASE_URL=postgresql+psycopg://privacyguard_platform_migrator:<MIGRATION_PASSWORD>@localhost:5432/privacyguard_platform
PRIVACYGUARD_RUN_POSTGRES_TESTS=0
PRIVACYGUARD_TEST_DATABASE_URL=postgresql+psycopg://privacyguard_platform_runtime:<RUNTIME_PASSWORD>@localhost:5432/privacyguard_platform
```

URL-encode reserved password characters. Never paste a populated URL into logs
or documentation.

## Schema migration

After discovery, review, and explicit approval, set the migration URL in the
current process and run:

```powershell
$env:PYTHONPATH = "src"
& ".\.venv\Scripts\python.exe" -m alembic current
& ".\.venv\Scripts\python.exe" -m alembic upgrade head
```

Alembic prints driver, user, host, port, and database without a password. For a
live PostgreSQL migration it also queries `current_database()` and refuses to
run unless the result is exactly `privacyguard_platform`.

The API never calls `Base.metadata.create_all()` for PostgreSQL. Alembic owns
production schema versions. Automatic table creation is limited to explicitly
injected SQLite tests.

## Legacy SQLite data

`privacyguard_platform.db` remains unchanged and available. A fresh PostgreSQL
database with new synthetic records is acceptable for this sprint; historical
copying is not part of normal startup or provisioning.

If a later migration is separately reviewed and explicitly approved,
`scripts/migrate_platform_sqlite.py` can copy the data. It opens SQLite using
`mode=ro` and `PRAGMA query_only`, requires an empty migrated target, and wraps
all PostgreSQL inserts in one transaction. Do not run it by default.

## Local startup

After the approved schema migration, set only the runtime URL and start:

```powershell
$env:PYTHONPATH = "src"
& ".\.venv\Scripts\uvicorn.exe" `
  privacyguard.platform.app:create_app --factory
```

`/health/live` verifies process liveness. `/health/ready` executes `SELECT 1`
and returns HTTP 503 with a generic message when connectivity fails. Runtime
never falls back to SQLite.

## Tests

Normal strict suite:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest -o addopts="" -q -W error
```

The PostgreSQL module is opt-in and performs approved synthetic writes followed
by scoped cleanup:

```powershell
$env:PRIVACYGUARD_RUN_POSTGRES_TESTS = "1"
& ".\.venv\Scripts\python.exe" -m pytest -o addopts="" -q -W error `
  tests/platform/test_postgresql_integration.py
```

Do not enable it before discovery, approval, provisioning, and Alembic upgrade.
