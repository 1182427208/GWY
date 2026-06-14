"""add gwy position analysis tables

Revision ID: a1b2c3d4e5f6
Revises: 5b7c1c2a9d10, 6b7d8d9e1f20
Create Date: 2026-05-29 00:00:00.000000

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = ("5b7c1c2a9d10", "6b7d8d9e1f20")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gwy_position_analysis_snapshot",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "title", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column(
            "source_sheet", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True
        ),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("selected_position_ids", sa.JSON(), nullable=False),
        sa.Column("visible_columns", sa.JSON(), nullable=False),
        sa.Column("notes", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_gwy_position_analysis_snapshot_title"),
        "gwy_position_analysis_snapshot",
        ["title"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_position_analysis_snapshot_user_id"),
        "gwy_position_analysis_snapshot",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_position_analysis_snapshot_source_sheet"),
        "gwy_position_analysis_snapshot",
        ["source_sheet"],
        unique=False,
    )

    op.create_table(
        "gwy_position_analysis_task",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False
        ),
        sa.Column(
            "stage", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("report_text", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("trace_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["snapshot_id"], ["gwy_position_analysis_snapshot.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_gwy_position_analysis_task_snapshot_id"),
        "gwy_position_analysis_task",
        ["snapshot_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_position_analysis_task_stage"),
        "gwy_position_analysis_task",
        ["stage"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_position_analysis_task_status"),
        "gwy_position_analysis_task",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_position_analysis_task_user_id"),
        "gwy_position_analysis_task",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "gwy_position_analysis_step",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column(
            "step_name", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False
        ),
        sa.Column(
            "status", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False
        ),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["gwy_position_analysis_task.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_gwy_position_analysis_step_step_name"),
        "gwy_position_analysis_step",
        ["step_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_position_analysis_step_status"),
        "gwy_position_analysis_step",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_position_analysis_step_task_id"),
        "gwy_position_analysis_step",
        ["task_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_gwy_position_analysis_step_task_id"),
        table_name="gwy_position_analysis_step",
    )
    op.drop_index(
        op.f("ix_gwy_position_analysis_step_step_name"),
        table_name="gwy_position_analysis_step",
    )
    op.drop_index(
        op.f("ix_gwy_position_analysis_step_status"),
        table_name="gwy_position_analysis_step",
    )
    op.drop_table("gwy_position_analysis_step")

    op.drop_index(
        op.f("ix_gwy_position_analysis_task_user_id"),
        table_name="gwy_position_analysis_task",
    )
    op.drop_index(
        op.f("ix_gwy_position_analysis_task_snapshot_id"),
        table_name="gwy_position_analysis_task",
    )
    op.drop_index(
        op.f("ix_gwy_position_analysis_task_status"),
        table_name="gwy_position_analysis_task",
    )
    op.drop_index(
        op.f("ix_gwy_position_analysis_task_stage"),
        table_name="gwy_position_analysis_task",
    )
    op.drop_table("gwy_position_analysis_task")

    op.drop_index(
        op.f("ix_gwy_position_analysis_snapshot_user_id"),
        table_name="gwy_position_analysis_snapshot",
    )
    op.drop_index(
        op.f("ix_gwy_position_analysis_snapshot_source_sheet"),
        table_name="gwy_position_analysis_snapshot",
    )
    op.drop_index(
        op.f("ix_gwy_position_analysis_snapshot_title"),
        table_name="gwy_position_analysis_snapshot",
    )
    op.drop_table("gwy_position_analysis_snapshot")
