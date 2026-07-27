"""add pipeline company attempt results

Revision ID: c9271bd38ea6
Revises: 77eab1ada604
Create Date: 2026-07-27 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c9271bd38ea6"
down_revision: str | Sequence[str] | None = "77eab1ada604"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "pipeline_company_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pipeline_run_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("pipeline_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempted_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("retry_after", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default="now()", nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default="now()", nullable=False),
        sa.CheckConstraint(
            "status IN ('succeeded', 'no_data', 'failed')",
            name="ck_pipeline_company_results_status",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pipeline_company_results_company_id"),
        "pipeline_company_results",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pipeline_company_results_pipeline_run_id"),
        "pipeline_company_results",
        ["pipeline_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_pipeline_company_results_pipeline_company",
        "pipeline_company_results",
        ["pipeline_name", "company_id"],
        unique=False,
    )
    op.create_index(
        "ix_pipeline_company_results_pipeline_retry_after",
        "pipeline_company_results",
        ["pipeline_name", "retry_after"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_pipeline_company_results_pipeline_retry_after",
        table_name="pipeline_company_results",
    )
    op.drop_index(
        "ix_pipeline_company_results_pipeline_company",
        table_name="pipeline_company_results",
    )
    op.drop_index(
        op.f("ix_pipeline_company_results_pipeline_run_id"),
        table_name="pipeline_company_results",
    )
    op.drop_index(
        op.f("ix_pipeline_company_results_company_id"),
        table_name="pipeline_company_results",
    )
    op.drop_table("pipeline_company_results")
