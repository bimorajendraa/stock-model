"""add company asset type

Revision ID: 4a8f2d1c6b90
Revises: c9271bd38ea6
Create Date: 2026-07-27 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4a8f2d1c6b90"
down_revision: str | Sequence[str] | None = "c9271bd38ea6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "companies",
        sa.Column("asset_type", sa.String(length=16), server_default="equity", nullable=False),
    )
    op.create_check_constraint(
        "ck_companies_asset_type",
        "companies",
        "asset_type IN ('equity', 'index', 'etf', 'other')",
    )
    op.create_index(op.f("ix_companies_asset_type"), "companies", ["asset_type"], unique=False)
    op.execute(
        "UPDATE companies SET asset_type = 'index' "
        "WHERE ticker IN ('I.GRADE', 'IDXBUMN20', 'IDXHIDIV20', 'IDXSMC.COM', 'IDXSMC.LIQ')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_companies_asset_type"), table_name="companies")
    op.drop_constraint("ck_companies_asset_type", "companies", type_="check")
    op.drop_column("companies", "asset_type")
