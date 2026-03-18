"""initial schema

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-03-18 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "a1b2c3d4e5f6"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    # --- companies ---
    op.create_table(
        "companies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("link", sa.String(2048), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "user_id", "normalized_name", name="uq_companies_user_id_normalized_name"
        ),
    )
    op.create_index(
        "ix_companies_user_id_normalized_name",
        "companies",
        ["user_id", "normalized_name"],
    )

    # --- applications ---
    op.create_table(
        "applications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "IN_PROGRESS",
                "APPLIED",
                "INTERVIEW",
                "OFFER",
                "REJECTED",
                name="applicationstatus",
            ),
            nullable=False,
        ),
        sa.Column("source_url", sa.String(2048), nullable=True),
        sa.Column("date_applied", sa.Date, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_applications_user_id_status", "applications", ["user_id", "status"]
    )
    op.create_index(
        "ix_applications_user_id_date_applied",
        "applications",
        ["user_id", "date_applied"],
    )
    op.create_index(
        "ix_applications_company_id", "applications", ["company_id"]
    )
    op.create_index(
        "ix_applications_user_id_source_url",
        "applications",
        ["user_id", "source_url"],
    )

    # --- interviews ---
    op.create_table(
        "interviews",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("application_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "round_type",
            sa.Enum(
                "PHONE",
                "TECHNICAL",
                "BEHAVIORAL",
                "SYSTEM_DESIGN",
                "FINAL",
                "OTHER",
                name="roundtype",
            ),
            nullable=False,
        ),
        sa.Column("scheduled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum("PASSED", "FAILED", "PENDING", name="interviewoutcome"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_interviews_application_id", "interviews", ["application_id"]
    )

    # --- job_descriptions ---
    op.create_table(
        "job_descriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("application_id", UUID(as_uuid=True), nullable=False),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column(
            "captured_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "application_id", name="uq_job_descriptions_application_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("job_descriptions")
    op.drop_index("ix_interviews_application_id", table_name="interviews")
    op.drop_table("interviews")
    op.drop_index("ix_applications_user_id_source_url", table_name="applications")
    op.drop_index("ix_applications_company_id", table_name="applications")
    op.drop_index("ix_applications_user_id_date_applied", table_name="applications")
    op.drop_index("ix_applications_user_id_status", table_name="applications")
    op.drop_table("applications")
    op.drop_index(
        "ix_companies_user_id_normalized_name", table_name="companies"
    )
    op.drop_table("companies")
    op.drop_table("users")

    sa.Enum(name="interviewoutcome").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="roundtype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="applicationstatus").drop(op.get_bind(), checkfirst=True)
