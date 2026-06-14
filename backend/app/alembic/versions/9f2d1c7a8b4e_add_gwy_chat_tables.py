"""add gwy chat tables

Revision ID: 9f2d1c7a8b4e
Revises: 8c1b8d8f4d3a
Create Date: 2026-05-27 18:20:00.000000

"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "9f2d1c7a8b4e"
down_revision = "8c1b8d8f4d3a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gwy_chat_session",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "title", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column(
            "last_intent",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=True,
        ),
        sa.Column(
            "active_topic",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column("mentioned_docs", sa.JSON(), nullable=False),
        sa.Column("summary", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            "summary_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_gwy_chat_session_active_topic"),
        "gwy_chat_session",
        ["active_topic"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_chat_session_created_at"),
        "gwy_chat_session",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_chat_session_last_intent"),
        "gwy_chat_session",
        ["last_intent"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_chat_session_title"),
        "gwy_chat_session",
        ["title"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_chat_session_user_id"),
        "gwy_chat_session",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "gwy_chat_message",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False
        ),
        sa.Column("content", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "intent", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True
        ),
        sa.Column("historical_reference", sa.Boolean(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("retrieval_trace", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["gwy_chat_session.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_gwy_chat_message_intent"),
        "gwy_chat_message",
        ["intent"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_chat_message_role"),
        "gwy_chat_message",
        ["role"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_chat_message_session_id"),
        "gwy_chat_message",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "gwy_rag_cache_entry",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column(
            "query_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["gwy_chat_session.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("query_hash"),
    )
    op.create_index(
        op.f("ix_gwy_rag_cache_entry_expires_at"),
        "gwy_rag_cache_entry",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_rag_cache_entry_query_hash"),
        "gwy_rag_cache_entry",
        ["query_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_rag_cache_entry_session_id"),
        "gwy_rag_cache_entry",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_gwy_rag_cache_entry_session_id"), table_name="gwy_rag_cache_entry")
    op.drop_index(op.f("ix_gwy_rag_cache_entry_query_hash"), table_name="gwy_rag_cache_entry")
    op.drop_index(op.f("ix_gwy_rag_cache_entry_expires_at"), table_name="gwy_rag_cache_entry")
    op.drop_table("gwy_rag_cache_entry")

    op.drop_index(op.f("ix_gwy_chat_message_session_id"), table_name="gwy_chat_message")
    op.drop_index(op.f("ix_gwy_chat_message_role"), table_name="gwy_chat_message")
    op.drop_index(op.f("ix_gwy_chat_message_intent"), table_name="gwy_chat_message")
    op.drop_table("gwy_chat_message")

    op.drop_index(op.f("ix_gwy_chat_session_user_id"), table_name="gwy_chat_session")
    op.drop_index(op.f("ix_gwy_chat_session_title"), table_name="gwy_chat_session")
    op.drop_index(op.f("ix_gwy_chat_session_last_intent"), table_name="gwy_chat_session")
    op.drop_index(op.f("ix_gwy_chat_session_created_at"), table_name="gwy_chat_session")
    op.drop_index(op.f("ix_gwy_chat_session_active_topic"), table_name="gwy_chat_session")
    op.drop_table("gwy_chat_session")
