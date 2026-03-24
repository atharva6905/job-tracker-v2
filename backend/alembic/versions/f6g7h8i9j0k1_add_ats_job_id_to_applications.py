"""add ats_job_id to applications

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-03-24 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "f6g7h8i9j0k1"
down_revision = "e5f6g7h8i9j0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("ats_job_id", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_applications_user_id_ats_job_id",
        "applications",
        ["user_id", "ats_job_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_applications_user_id_ats_job_id", table_name="applications")
    op.drop_column("applications", "ats_job_id")
