"""taxonomy_tag_stats

Revision ID: 0001_taxonomy_tag_stats
Revises:
Create Date: 2026-11-25

一张结果表：每个标签每天一行。唯一约束 (tag_id, stat_date) 是幂等的结构性保证 ——
重跑同一天只能覆盖，不可能插重。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_taxonomy_tag_stats"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taxonomy_tag_stats",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dict_code", sa.String(64), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("counts", postgresql.JSONB(), nullable=False,
                  comment='{"company":n,"supply_demand":n,"capability_card":n,"activity":n}'),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_30d", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tag_id", "stat_date", name="uq_tag_stats_tag_day"),
        sa.CheckConstraint("total >= 0 AND new_30d >= 0", name="ck_tag_stats_non_negative"),
        sa.CheckConstraint("new_30d <= total", name="ck_tag_stats_window_subset"),
    )
    op.create_index("ix_tag_stats_dict_day", "taxonomy_tag_stats", ["dict_code", "stat_date"])
    op.create_index("ix_tag_stats_day_total", "taxonomy_tag_stats", ["stat_date", "total"])


def downgrade() -> None:
    op.drop_index("ix_tag_stats_day_total", table_name="taxonomy_tag_stats")
    op.drop_index("ix_tag_stats_dict_day", table_name="taxonomy_tag_stats")
    op.drop_table("taxonomy_tag_stats")
