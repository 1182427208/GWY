"""add GwyPilot evaluation tables

Revision ID: f1e2d3c4b5a6
Revises: 2a6d4f1c9b77
"""

import sqlalchemy as sa
from alembic import op

revision = "f1e2d3c4b5a6"
down_revision = "2a6d4f1c9b77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gwy_eval_dataset",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("split", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("cases_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gwy_eval_dataset_user_id", "gwy_eval_dataset", ["user_id"])
    op.create_index("ix_gwy_eval_dataset_split", "gwy_eval_dataset", ["split"])
    op.create_index("ix_gwy_eval_dataset_task_type", "gwy_eval_dataset", ["task_type"])
    op.create_index("ix_gwy_eval_dataset_status", "gwy_eval_dataset", ["status"])
    op.create_table(
        "gwy_eval_run",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=True),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("report_text", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["gwy_eval_dataset.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gwy_eval_run_user_id", "gwy_eval_run", ["user_id"])
    op.create_index("ix_gwy_eval_run_dataset_id", "gwy_eval_run", ["dataset_id"])
    op.create_index("ix_gwy_eval_run_source_id", "gwy_eval_run", ["source_id"])
    op.create_index("ix_gwy_eval_run_status", "gwy_eval_run", ["status"])
    op.create_table(
        "gwy_eval_case_result",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("scores_json", sa.JSON(), nullable=False),
        sa.Column("observation_json", sa.JSON(), nullable=False),
        sa.Column("failure_reasons", sa.JSON(), nullable=False),
        sa.Column("trace_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["gwy_eval_run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gwy_eval_case_result_run_id", "gwy_eval_case_result", ["run_id"])
    op.create_index("ix_gwy_eval_case_result_case_id", "gwy_eval_case_result", ["case_id"])
    op.create_index("ix_gwy_eval_case_result_status", "gwy_eval_case_result", ["status"])


def downgrade() -> None:
    op.drop_table("gwy_eval_case_result")
    op.drop_table("gwy_eval_run")
    op.drop_table("gwy_eval_dataset")
