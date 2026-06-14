"""add feishu webhook to gwy user profile

Revision ID: d1e2f3a4b5c6
Revises: a1b2c3d4e5f6
Create Date: 2026-05-30 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gwy_user_profile",
        sa.Column("feishu_webhook_url", sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gwy_user_profile", "feishu_webhook_url")
