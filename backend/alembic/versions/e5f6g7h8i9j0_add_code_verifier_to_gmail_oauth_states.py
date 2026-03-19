"""add code_verifier to gmail_oauth_states

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-03-19 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "e5f6g7h8i9j0"
down_revision = "d4e5f6g7h8i9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gmail_oauth_states",
        sa.Column("code_verifier", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gmail_oauth_states", "code_verifier")
