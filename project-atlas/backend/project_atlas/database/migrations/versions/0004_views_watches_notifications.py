"""Saved views, entity watches and in-app notifications.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ts = sa.DateTime(timezone=True)
    op.create_table(
        "saved_views",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(40), sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("created_at", ts, nullable=False),
    )
    op.create_index("ix_saved_views_user_id", "saved_views", ["user_id"])
    op.create_table(
        "watches",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("project_id", sa.String(40), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.String(40), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", ts, nullable=False),
        sa.UniqueConstraint("user_id", "entity_id"),
    )
    op.create_index("ix_watches_project_id", "watches", ["project_id"])
    op.create_index("ix_watches_entity_id", "watches", ["entity_id"])
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(40), sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("link", sa.String(1024)),
        sa.Column("details", sa.JSON, nullable=False),
        sa.Column("read_at", ts),
        sa.Column("created_at", ts, nullable=False),
    )
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "read_at"])


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("watches")
    op.drop_table("saved_views")
