"""add workday_tenant to applications

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2026-03-24 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "g7h8i9j0k1l2"
down_revision = "f6g7h8i9j0k1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("workday_tenant", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_applications_user_id_workday_tenant",
        "applications",
        ["user_id", "workday_tenant"],
    )


def downgrade() -> None:
    op.drop_index("ix_applications_user_id_workday_tenant", table_name="applications")
    op.drop_column("applications", "workday_tenant")
