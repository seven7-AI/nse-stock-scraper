"""create stock_data table

Revision ID: 20260214_0001
Revises:
Create Date: 2026-02-14 00:01:00
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260214_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stock_data",
        sa.Column("ticker_symbol", sa.String(length=20), nullable=False),
        sa.Column("stock_name", sa.String(length=255), nullable=False),
        sa.Column("stock_price", sa.Float(), nullable=False),
        sa.Column("stock_change", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("ticker_symbol", name="pk_stock_data"),
    )
    op.create_index("ix_stock_data_created_at", "stock_data", ["created_at"], unique=False)


def downgrade():
    op.drop_index("ix_stock_data_created_at", table_name="stock_data")
    op.drop_table("stock_data")
