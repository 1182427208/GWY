"""align study plan task foreign key with position analysis tasks

Revision ID: 2a6d4f1c9b77
Revises: 7c2f9b1a4d33
Create Date: 2026-06-13 00:00:00.000000
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "2a6d4f1c9b77"
down_revision = "7c2f9b1a4d33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "gwy_study_plan_task_id_fkey",
        "gwy_study_plan",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "gwy_study_plan_task_id_fkey",
        "gwy_study_plan",
        "gwy_position_analysis_task",
        ["task_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "gwy_study_plan_task_id_fkey",
        "gwy_study_plan",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "gwy_study_plan_task_id_fkey",
        "gwy_study_plan",
        "gwy_recommendation_task",
        ["task_id"],
        ["id"],
    )
