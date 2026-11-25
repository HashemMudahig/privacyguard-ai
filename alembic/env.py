import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from logging.config import fileConfig

from sqlalchemy import create_engine, text
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
from privacyguard.platform.models import Base
from privacyguard.platform.database import (
    PLATFORM_DATABASE_NAME,
    resolve_database_url,
    sanitized_database_identity,
)

target_metadata = Base.metadata
database_url = resolve_database_url(for_migrations=True)
print(f"Alembic configured target: {sanitized_database_identity(database_url)}")

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = create_engine(database_url, future=True, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        if connection.dialect.name == "postgresql":
            actual_database = connection.execute(
                text("SELECT current_database()")
            ).scalar_one()
            if actual_database != PLATFORM_DATABASE_NAME:
                raise RuntimeError(
                    "Refusing migration: connected PostgreSQL database is not "
                    f"'{PLATFORM_DATABASE_NAME}'"
                )
            print(
                "Alembic live target confirmed: "
                f"database={actual_database} dialect={connection.dialect.name}"
            )
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
