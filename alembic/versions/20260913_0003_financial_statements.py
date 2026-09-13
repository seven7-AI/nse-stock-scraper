"""financial statements and fundamentals snapshots: append-only, point-in-time

Revision ID: 20260913_0003
Revises: 20260912_0002
Create Date: 2026-09-13

Purely additive. Adds financial_statements (line items from the stockanalysis
income statement / balance sheet / cash-flow statement / ratios pages, annual and
quarterly, keyed on the displayed value so restatements append rather than overwrite)
and fundamental_snapshots (the daily per-view metric JSON that stockanalysis_stocks
otherwise overwrites).

The DDL is the same string SQLiteBackend._create_schema() executes on every open(), so
running the scraper once or `alembic upgrade head` reach the same schema and doing both
is harmless (every statement is IF NOT EXISTS). tests/test_sqlite_backend.py asserts
this file, the runtime DDL and sql/sqlite/003_financials.sql describe identical tables.
"""

from alembic import op

from nse_scraper.db.canonical_schema import FINANCIALS_SCHEMA_SQL, FINANCIALS_TABLES

# revision identifiers, used by Alembic.
revision = "20260913_0003"
down_revision = "20260912_0002"
branch_labels = None
depends_on = None


def upgrade():
    for statement in _statements(FINANCIALS_SCHEMA_SQL):
        op.execute(statement)


def downgrade():
    for table in reversed(FINANCIALS_TABLES):
        op.execute("DROP TABLE IF EXISTS {}".format(table))


def _statements(script):
    """Split the schema script into individual statements for op.execute()."""
    return [s.strip() for s in script.split(";") if s.strip()]
