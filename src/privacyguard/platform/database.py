from __future__ import annotations

import os
from typing import Final

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base

RUNTIME_DATABASE_URL_ENV: Final = "PRIVACYGUARD_DATABASE_URL"
MIGRATION_DATABASE_URL_ENV: Final = "PRIVACYGUARD_MIGRATION_DATABASE_URL"
ALLOW_SQLITE_ENV: Final = "PRIVACYGUARD_ALLOW_SQLITE"
PLATFORM_DATABASE_NAME: Final = "privacyguard_platform"


def _is_true(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def validate_database_url(url: str, *, allow_sqlite: bool = False) -> str:
    """Validate platform isolation without ever rendering credentials."""
    parsed = make_url(url)
    backend = parsed.get_backend_name()
    if backend == "postgresql":
        if parsed.database != PLATFORM_DATABASE_NAME:
            raise ValueError(
                "The platform PostgreSQL URL must target the dedicated "
                f"'{PLATFORM_DATABASE_NAME}' database"
            )
        return url
    if backend == "sqlite" and allow_sqlite:
        return url
    if backend == "sqlite":
        raise ValueError(
            "SQLite is restricted to isolated tests; set "
            f"{ALLOW_SQLITE_ENV}=1 only for explicit local test tooling"
        )
    raise ValueError("The platform database must use PostgreSQL or test-only SQLite")


def sanitized_database_identity(url: str) -> str:
    """Return connection identity fields without rendering a password."""
    parsed = make_url(url)
    return " ".join(
        (
            f"driver={parsed.drivername}",
            f"user={parsed.username or '<default>'}",
            f"host={parsed.host or '<local>'}",
            f"port={parsed.port or '<default>'}",
            f"database={parsed.database or '<none>'}",
        )
    )


def resolve_database_url(
    explicit_url: str | None = None,
    *,
    for_migrations: bool = False,
) -> str:
    """Resolve the shared runtime/Alembic database target from the environment."""
    if explicit_url is not None:
        return validate_database_url(explicit_url, allow_sqlite=True)

    variable = MIGRATION_DATABASE_URL_ENV if for_migrations else RUNTIME_DATABASE_URL_ENV
    url = os.getenv(variable)
    if not url:
        raise RuntimeError(f"Set {variable} to a SQLAlchemy database URL")
    return validate_database_url(url, allow_sqlite=_is_true(os.getenv(ALLOW_SQLITE_ENV)))


def create_engine_from_url(url: str) -> Engine:
    if url == "sqlite:///:memory:":
        engine = create_engine(
            url,
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        engine = create_engine(
            url,
            future=True,
            connect_args=connect_args,
            pool_pre_ping=True,
        )
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()
    return engine


def create_session_factory(url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=create_engine_from_url(url), expire_on_commit=False, future=True)


def init_test_schema(engine: Engine) -> None:
    """Create ORM tables only for an explicitly injected SQLite test engine."""
    if engine.dialect.name != "sqlite":
        raise ValueError("Runtime PostgreSQL schemas must be managed by Alembic")
    Base.metadata.create_all(bind=engine)


class PlatformDatabase:
    def __init__(self, url: str):
        self.engine = create_engine_from_url(url)
        self.session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            future=True,
        )

    def session(self) -> Session:
        return self.session_factory()

    def dispose(self) -> None:
        self.engine.dispose()
