from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from nse_scraper.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url():
    """Where migrations run.

    Defaults to the SQLite runtime database the scraper actually writes to
    (SQLITE_DB_PATH, same variable the backend reads), so `alembic upgrade head`
    with no extra configuration touches the real store. SQL_DATABASE_URL still
    overrides it for anyone pointing at Postgres.

    The URL in alembic.ini is kept only as a last-resort fallback; before this
    change it silently targeted a Postgres on localhost:5432 that belongs to a
    different project.
    """
    explicit = os.getenv("SQL_DATABASE_URL")
    if explicit:
        return explicit
    sqlite_path = os.getenv("SQLITE_DB_PATH", "data/nse_scraper.sqlite3")
    if sqlite_path:
        return "sqlite:///" + os.path.abspath(sqlite_path)
    return config.get_main_option("sqlalchemy.url")


def run_migrations_offline():
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # render_as_batch: SQLite cannot ALTER most things in place; batch mode
        # rebuilds the table under the hood so downgrade() works there too.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
