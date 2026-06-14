"""add gwy chat attachments

Revision ID: 6b7d8d9e1f20
Revises: 9f2d1c7a8b4e
Create Date: 2026-05-28 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "6b7d8d9e1f20"
down_revision = "9f2d1c7a8b4e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gwy_chat_attachment",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column(
            "file_name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column(
            "original_name",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "attachment_type",
            sqlmodel.sql.sqltypes.AutoString(length=32),
            nullable=False,
        ),
        sa.Column(
            "mime_type", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False
        ),
        sa.Column(
            "file_path", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=False
        ),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("summary", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("extracted_text", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            "extraction_status",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=False,
        ),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["gwy_chat_session.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_gwy_chat_attachment_attachment_type"),
        "gwy_chat_attachment",
        ["attachment_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_chat_attachment_created_at"),
        "gwy_chat_attachment",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_chat_attachment_extraction_status"),
        "gwy_chat_attachment",
        ["extraction_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_chat_attachment_file_name"),
        "gwy_chat_attachment",
        ["file_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_chat_attachment_mime_type"),
        "gwy_chat_attachment",
        ["mime_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_chat_attachment_session_id"),
        "gwy_chat_attachment",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_gwy_chat_attachment_session_id"),
        table_name="gwy_chat_attachment",
    )
    op.drop_index(
        op.f("ix_gwy_chat_attachment_mime_type"),
        table_name="gwy_chat_attachment",
    )
    op.drop_index(
        op.f("ix_gwy_chat_attachment_file_name"),
        table_name="gwy_chat_attachment",
    )
    op.drop_index(
        op.f("ix_gwy_chat_attachment_extraction_status"),
        table_name="gwy_chat_attachment",
    )
    op.drop_index(
        op.f("ix_gwy_chat_attachment_created_at"),
        table_name="gwy_chat_attachment",
    )
    op.drop_index(
        op.f("ix_gwy_chat_attachment_attachment_type"),
        table_name="gwy_chat_attachment",
    )
    op.drop_table("gwy_chat_attachment")
