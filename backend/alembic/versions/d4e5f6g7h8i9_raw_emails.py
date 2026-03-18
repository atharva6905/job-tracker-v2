"""raw_emails

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-03-18 00:03:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "d4e5f6g7h8i9"
down_revision = "c3d4e5f6g7h8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_emails",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email_account_id", UUID(as_uuid=True), nullable=False),
        sa.Column("gmail_message_id", sa.String(255), nullable=False),
        sa.Column("subject", sa.Text, nullable=True),
        sa.Column("sender", sa.String(255), nullable=True),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("body_snippet", sa.Text, nullable=True),
        sa.Column("gemini_signal", sa.String(50), nullable=True),
        sa.Column("gemini_confidence", sa.Float, nullable=True),
        sa.Column("linked_application_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["email_account_id"], ["email_accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["linked_application_id"], ["applications.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("gmail_message_id", name="uq_raw_emails_gmail_message_id"),
    )
    op.create_index(
        "ix_raw_emails_email_account_id_received_at",
        "raw_emails",
        ["email_account_id", "received_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_raw_emails_email_account_id_received_at", table_name="raw_emails"
    )
    op.drop_table("raw_emails")
