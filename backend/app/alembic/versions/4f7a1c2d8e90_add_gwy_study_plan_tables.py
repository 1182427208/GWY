"""add gwy study plan tables

Revision ID: 4f7a1c2d8e90
Revises: a1b2c3d4e5f6
Create Date: 2026-06-13 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision = "4f7a1c2d8e90"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gwy_study_plan",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("exam_type", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column("exam_year", sa.Integer(), nullable=True),
        sa.Column("estimated_exam_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("study_hours_per_day", sa.Integer(), nullable=False),
        sa.Column("total_weeks", sa.Integer(), nullable=False),
        sa.Column("profile_snapshot", sa.JSON(), nullable=False),
        sa.Column("position_ids", sa.JSON(), nullable=False),
        sa.Column("report_markdown", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["gwy_recommendation_task.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_gwy_study_plan_exam_year"),
        "gwy_study_plan",
        ["exam_year"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_study_plan_status"),
        "gwy_study_plan",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_study_plan_task_id"),
        "gwy_study_plan",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_study_plan_title"),
        "gwy_study_plan",
        ["title"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_study_plan_user_id"),
        "gwy_study_plan",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "gwy_study_phase",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("study_plan_id", sa.Uuid(), nullable=False),
        sa.Column("phase_order", sa.Integer(), nullable=False),
        sa.Column("phase_name", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column("phase_goal", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("week_start", sa.Integer(), nullable=False),
        sa.Column("week_end", sa.Integer(), nullable=False),
        sa.Column("focus_subjects", sa.JSON(), nullable=False),
        sa.Column("study_hours_per_day", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["study_plan_id"], ["gwy_study_plan.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_gwy_study_phase_study_plan_id"),
        "gwy_study_phase",
        ["study_plan_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_study_phase_phase_order"),
        "gwy_study_phase",
        ["phase_order"],
        unique=False,
    )

    op.create_table(
        "gwy_study_subject",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("study_plan_id", sa.Uuid(), nullable=False),
        sa.Column("subject_name", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column("subject_category", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("weight_percent", sa.Integer(), nullable=False),
        sa.Column("total_hours", sa.Integer(), nullable=False),
        sa.Column("checklist_items", sa.JSON(), nullable=False),
        sa.Column("resources", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["study_plan_id"], ["gwy_study_plan.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_gwy_study_subject_study_plan_id"),
        "gwy_study_subject",
        ["study_plan_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_study_subject_subject_name"),
        "gwy_study_subject",
        ["subject_name"],
        unique=False,
    )

    op.create_table(
        "gwy_study_task",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("study_plan_id", sa.Uuid(), nullable=False),
        sa.Column("phase_id", sa.Uuid(), nullable=True),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("subject", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column("task_title", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("task_description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["study_plan_id"], ["gwy_study_plan.id"]),
        sa.ForeignKeyConstraint(["phase_id"], ["gwy_study_phase.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_gwy_study_task_study_plan_id"),
        "gwy_study_task",
        ["study_plan_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_study_task_week_number"),
        "gwy_study_task",
        ["week_number"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gwy_study_task_day_of_week"),
        "gwy_study_task",
        ["day_of_week"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_gwy_study_task_day_of_week"), table_name="gwy_study_task")
    op.drop_index(op.f("ix_gwy_study_task_week_number"), table_name="gwy_study_task")
    op.drop_index(op.f("ix_gwy_study_task_study_plan_id"), table_name="gwy_study_task")
    op.drop_table("gwy_study_task")

    op.drop_index(op.f("ix_gwy_study_subject_subject_name"), table_name="gwy_study_subject")
    op.drop_index(op.f("ix_gwy_study_subject_study_plan_id"), table_name="gwy_study_subject")
    op.drop_table("gwy_study_subject")

    op.drop_index(op.f("ix_gwy_study_phase_phase_order"), table_name="gwy_study_phase")
    op.drop_index(op.f("ix_gwy_study_phase_study_plan_id"), table_name="gwy_study_phase")
    op.drop_table("gwy_study_phase")

    op.drop_index(op.f("ix_gwy_study_plan_user_id"), table_name="gwy_study_plan")
    op.drop_index(op.f("ix_gwy_study_plan_title"), table_name="gwy_study_plan")
    op.drop_index(op.f("ix_gwy_study_plan_task_id"), table_name="gwy_study_plan")
    op.drop_index(op.f("ix_gwy_study_plan_status"), table_name="gwy_study_plan")
    op.drop_index(op.f("ix_gwy_study_plan_exam_year"), table_name="gwy_study_plan")
    op.drop_table("gwy_study_plan")
