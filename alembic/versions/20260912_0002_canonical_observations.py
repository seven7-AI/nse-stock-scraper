"""canonical stock observations: instruments, aliases, one row per (ticker, trade_date)

Revision ID: 20260912_0002
Revises: 20260214_0001
Create Date: 2026-09-12

Purely additive. The two per-ticker tables (stock_data, stockanalysis_stocks) are not
touched; nse-be keeps reading them exactly as before.

The DDL is the same string SQLiteBackend._create_schema() executes on every open(), so
a database can be brought to this revision either by running the scraper once or by
`alembic upgrade head` — and running both is harmless (every statement is
IF NOT EXISTS). tests/test_sqlite_backend.py asserts this file, the runtime DDL and
sql/sqlite/002_canonical.sql describe identical tables.

Note on 20260214_0001: that revision describes the original Postgres stock_data table
and has never been executed against the SQLite runtime, whose tables are created by
_create_schema(). It is `alembic stamp`ed rather than run. This is the first revision
that actually executes.
"""

from alembic import op

from nse_scraper.db.canonical_schema import CANONICAL_SCHEMA_SQL, CANONICAL_TABLES

# revision identifiers, used by Alembic.
revision = "20260912_0002"
down_revision = "20260214_0001"
branch_labels = None
depends_on = None


def upgrade():
    for statement in _statements(CANONICAL_SCHEMA_SQL):
        op.execute(statement)


def downgrade():
    # Reverse dependency order: observations reference instruments; conflicts reference
    # observations. Only the five tables this revision introduced are removed.
    for table in reversed(CANONICAL_TABLES):
        op.execute("DROP TABLE IF EXISTS {}".format(table))


def _statements(script):
    """Split the schema script into individual statements for op.execute()."""
    return [s.strip() for s in script.split(";") if s.strip()]
