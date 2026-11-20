from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    override = config.attributes.get("url")
    if override:
        return str(override)
    settings = get_settings()
    return settings.migrations_database_url or settings.database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(
        _url(),
        poolclass=pool.NullPool,
        hide_parameters=True,
        # Fail fast instead of queueing behind live traffic while holding up
        # every other query on the table; retry the deploy instead.
        connect_args={"options": "-c lock_timeout=10s -c statement_timeout=5min"},
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
