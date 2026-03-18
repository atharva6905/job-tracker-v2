"""gmail_oauth_states

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-18 00:01:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "b2c3d4e5f6g7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gmail_oauth_states",
        sa.Column("state_token", sa.String(255), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_gmail_oauth_states_user_id", "gmail_oauth_states", ["user_id"])
    op.create_index("ix_gmail_oauth_states_expires_at", "gmail_oauth_states", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_gmail_oauth_states_expires_at", table_name="gmail_oauth_states")
    op.drop_index("ix_gmail_oauth_states_user_id", table_name="gmail_oauth_states")
    op.drop_table("gmail_oauth_states")
