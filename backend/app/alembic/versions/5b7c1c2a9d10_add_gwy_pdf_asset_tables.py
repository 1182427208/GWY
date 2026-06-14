"""add gwy pdf asset tables

Revision ID: 5b7c1c2a9d10
Revises: 9f2d1c7a8b4e
Create Date: 2026-05-27 21:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "5b7c1c2a9d10"
down_revision = "9f2d1c7a8b4e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gwy_pdf_asset",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_type", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("source_file", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=False),
        sa.Column("image_path", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=True),
        sa.Column("nearby_text", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("summary", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("ocr_text", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("extraction_status", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("linked_chunk_ids", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_gwy_pdf_asset_asset_type"),
        "gwy_pdf_asset",
        ["asset_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_pdf_asset_extraction_status"),
        "gwy_pdf_asset",
        ["extraction_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_pdf_asset_page"),
        "gwy_pdf_asset",
        ["page"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_pdf_asset_source_file"),
        "gwy_pdf_asset",
        ["source_file"],
        unique=False,
    )

    op.create_table(
        "gwy_pdf_table",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_file", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=False),
        sa.Column("columns", sa.JSON(), nullable=False),
        sa.Column("markdown_content", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("table_image_path", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=True),
        sa.Column("extraction_status", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("is_cross_page", sa.Boolean(), nullable=False),
        sa.Column("source_pages", sa.JSON(), nullable=False),
        sa.Column("linked_chunk_ids", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_gwy_pdf_table_extraction_status"),
        "gwy_pdf_table",
        ["extraction_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_pdf_table_page_end"),
        "gwy_pdf_table",
        ["page_end"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_pdf_table_page_start"),
        "gwy_pdf_table",
        ["page_start"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_pdf_table_source_file"),
        "gwy_pdf_table",
        ["source_file"],
        unique=False,
    )

    op.create_table(
        "gwy_pdf_table_row",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("table_id", sa.Uuid(), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("row_text", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("row_json", sa.JSON(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["table_id"], ["gwy_pdf_table.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_gwy_pdf_table_row_page"),
        "gwy_pdf_table_row",
        ["page"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_pdf_table_row_row_index"),
        "gwy_pdf_table_row",
        ["row_index"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_pdf_table_row_table_id"),
        "gwy_pdf_table_row",
        ["table_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_gwy_pdf_table_row_table_id"), table_name="gwy_pdf_table_row")
    op.drop_index(op.f("ix_gwy_pdf_table_row_row_index"), table_name="gwy_pdf_table_row")
    op.drop_index(op.f("ix_gwy_pdf_table_row_page"), table_name="gwy_pdf_table_row")
    op.drop_table("gwy_pdf_table_row")

    op.drop_index(op.f("ix_gwy_pdf_table_source_file"), table_name="gwy_pdf_table")
    op.drop_index(op.f("ix_gwy_pdf_table_page_start"), table_name="gwy_pdf_table")
    op.drop_index(op.f("ix_gwy_pdf_table_page_end"), table_name="gwy_pdf_table")
    op.drop_index(op.f("ix_gwy_pdf_table_extraction_status"), table_name="gwy_pdf_table")
    op.drop_table("gwy_pdf_table")

    op.drop_index(op.f("ix_gwy_pdf_asset_source_file"), table_name="gwy_pdf_asset")
    op.drop_index(op.f("ix_gwy_pdf_asset_page"), table_name="gwy_pdf_asset")
    op.drop_index(op.f("ix_gwy_pdf_asset_extraction_status"), table_name="gwy_pdf_asset")
    op.drop_index(op.f("ix_gwy_pdf_asset_asset_type"), table_name="gwy_pdf_asset")
    op.drop_table("gwy_pdf_asset")
