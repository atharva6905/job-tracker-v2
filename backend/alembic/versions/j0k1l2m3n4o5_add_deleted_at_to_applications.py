"""add deleted_at to applications

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-03-25 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "j0k1l2m3n4o5"
down_revision = "i9j0k1l2m3n4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_applications_user_id_deleted_at",
        "applications",
        ["user_id", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_applications_user_id_deleted_at", table_name="applications")
    op.drop_column("applications", "deleted_at")
