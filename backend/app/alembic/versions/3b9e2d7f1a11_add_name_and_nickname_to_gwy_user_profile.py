"""add name and nickname to gwy user profile

Revision ID: 3b9e2d7f1a11
Revises: d1e2f3a4b5c6
Create Date: 2026-06-12 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "3b9e2d7f1a11"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gwy_user_profile",
        sa.Column("name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "gwy_user_profile",
        sa.Column("nickname", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gwy_user_profile", "nickname")
    op.drop_column("gwy_user_profile", "name")
