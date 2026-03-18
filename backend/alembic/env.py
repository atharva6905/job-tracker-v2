import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Uses DATABASE_URL_DIRECT (port 5432, direct connection).
# Do NOT use DATABASE_URL here — PgBouncer (port 6543) does not support
# DDL transactions that Alembic requires.
from dotenv import load_dotenv

load_dotenv()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import Base from database so Alembic can detect models
from app.database import Base  # noqa: E402

# Import all models so they register with Base.metadata
from app.models import user, company, application, interview, job_description  # noqa: E402, F401
from app.models import gmail_oauth_state, email_account  # noqa: E402, F401

target_metadata = Base.metadata

database_url_direct = os.environ["DATABASE_URL_DIRECT"]


def run_migrations_offline() -> None:
    context.configure(
        url=database_url_direct,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = database_url_direct
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
