"""add news entity match audit

Revision ID: b13d9e5a72c4
Revises: 4a8f2d1c6b90
Create Date: 2026-07-27 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b13d9e5a72c4"
down_revision: str | Sequence[str] | None = "4a8f2d1c6b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("news_entities", sa.Column("match_method", sa.String(length=32), nullable=True))
    op.add_column("news_entities", sa.Column("matched_text", sa.String(length=256), nullable=True))


def downgrade() -> None:
    op.drop_column("news_entities", "matched_text")
    op.drop_column("news_entities", "match_method")
