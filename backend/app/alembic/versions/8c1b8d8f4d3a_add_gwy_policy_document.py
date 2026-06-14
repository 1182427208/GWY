"""add gwy policy document

Revision ID: 8c1b8d8f4d3a
Revises: c3f6adfcebb2
Create Date: 2026-05-27 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "8c1b8d8f4d3a"
down_revision = "c3f6adfcebb2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gwy_policy_document",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "source_file", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False
        ),
        sa.Column(
            "doc_title", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column(
            "doc_group", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column(
            "doc_type", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column(
            "exam_type", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column(
            "province", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column(
            "milvus_collection",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "embedding_status",
            sqlmodel.sql.sqltypes.AutoString(length=32),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_gwy_policy_document_doc_group"),
        "gwy_policy_document",
        ["doc_group"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_policy_document_doc_title"),
        "gwy_policy_document",
        ["doc_title"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_policy_document_doc_type"),
        "gwy_policy_document",
        ["doc_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_policy_document_embedding_status"),
        "gwy_policy_document",
        ["embedding_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_policy_document_exam_type"),
        "gwy_policy_document",
        ["exam_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_policy_document_milvus_collection"),
        "gwy_policy_document",
        ["milvus_collection"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_policy_document_source_file"),
        "gwy_policy_document",
        ["source_file"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_policy_document_year"),
        "gwy_policy_document",
        ["year"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_gwy_policy_document_year"), table_name="gwy_policy_document"
    )
    op.drop_index(
        op.f("ix_gwy_policy_document_source_file"),
        table_name="gwy_policy_document",
    )
    op.drop_index(
        op.f("ix_gwy_policy_document_milvus_collection"),
        table_name="gwy_policy_document",
    )
    op.drop_index(
        op.f("ix_gwy_policy_document_exam_type"), table_name="gwy_policy_document"
    )
    op.drop_index(
        op.f("ix_gwy_policy_document_embedding_status"),
        table_name="gwy_policy_document",
    )
    op.drop_index(
        op.f("ix_gwy_policy_document_doc_type"), table_name="gwy_policy_document"
    )
    op.drop_index(
        op.f("ix_gwy_policy_document_doc_title"), table_name="gwy_policy_document"
    )
    op.drop_index(
        op.f("ix_gwy_policy_document_doc_group"), table_name="gwy_policy_document"
    )
    op.drop_table("gwy_policy_document")

