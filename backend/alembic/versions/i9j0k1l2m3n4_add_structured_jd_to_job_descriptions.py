"""add structured_jd to job_descriptions

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-03-25 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "i9j0k1l2m3n4"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_descriptions",
        sa.Column("structured_jd", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("job_descriptions", "structured_jd")
