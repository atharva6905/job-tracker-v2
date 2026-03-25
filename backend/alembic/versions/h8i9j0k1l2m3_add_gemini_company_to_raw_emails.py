"""add gemini_company to raw_emails

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-03-25 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "h8i9j0k1l2m3"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "raw_emails",
        sa.Column("gemini_company", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("raw_emails", "gemini_company")
