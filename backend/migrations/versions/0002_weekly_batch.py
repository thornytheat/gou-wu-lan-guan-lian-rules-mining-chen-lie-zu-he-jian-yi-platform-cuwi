"""周度批次对比：小票批次 / 规则血缘 / 对比快照 + 批次关联列。

Revision ID: 0002_weekly_batch
Revises: 0001_initial
Create Date: 2026-11-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_weekly_batch"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

SCHEMA = "basketrule"


def upgrade() -> None:
    op.create_table(
        "basket_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_code", sa.String(60), nullable=False, unique=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="import"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("basket_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("imported_filename", sa.String(200), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("imported_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey(f"{SCHEMA}.users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_basket_batches_code", "basket_batches", ["batch_code"], schema=SCHEMA)
    op.create_index("ix_basket_batches_fingerprint", "basket_batches", ["content_fingerprint"], schema=SCHEMA)

    op.add_column(
        "order_baskets",
        sa.Column("batch_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey(f"{SCHEMA}.basket_batches.id"), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("ix_order_baskets_batch_id", "order_baskets", ["batch_id"], schema=SCHEMA)

    op.add_column("mining_runs", sa.Column("batch_ids", postgresql.JSONB(),
                                           nullable=False, server_default="[]"), schema=SCHEMA)
    op.add_column("mining_runs", sa.Column("sample_start", sa.DateTime(timezone=True),
                                           nullable=True), schema=SCHEMA)
    op.add_column("mining_runs", sa.Column("sample_end", sa.DateTime(timezone=True),
                                           nullable=True), schema=SCHEMA)

    op.create_table(
        "rule_lineage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("rule_identity", sa.String(120), nullable=False),
        sa.Column("baseline_run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey(f"{SCHEMA}.mining_runs.id"), nullable=False),
        sa.Column("current_run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey(f"{SCHEMA}.mining_runs.id"), nullable=False),
        sa.Column("baseline_rule_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey(f"{SCHEMA}.rule_candidates.id"), nullable=False),
        sa.Column("current_rule_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey(f"{SCHEMA}.rule_candidates.id"), nullable=False),
        sa.Column("change_type", sa.String(20), nullable=False),
        sa.Column("baseline_status", sa.String(20), nullable=True),
        sa.Column("baseline_reason", sa.Text(), nullable=True),
        sa.Column("baseline_reviewer", sa.String(120), nullable=False, server_default=""),
        sa.Column("baseline_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("in_published_plan", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_rule_lineage_identity", "rule_lineage", ["rule_identity"], schema=SCHEMA)
    op.create_index("ix_rule_lineage_current", "rule_lineage", ["current_rule_id"], schema=SCHEMA)

    op.create_table(
        "run_comparisons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("comparison_key", sa.String(120), nullable=False, unique=True),
        sa.Column("baseline_run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey(f"{SCHEMA}.mining_runs.id"), nullable=False),
        sa.Column("current_run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey(f"{SCHEMA}.mining_runs.id"), nullable=False),
        sa.Column("counts", postgresql.JSONB(), nullable=False),
        sa.Column("baseline_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("current_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("changes", postgresql.JSONB(), nullable=False),
        sa.Column("affected_slots", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_run_comparisons_key", "run_comparisons", ["comparison_key"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_run_comparisons_key", table_name="run_comparisons", schema=SCHEMA)
    op.drop_table("run_comparisons", schema=SCHEMA)
    op.drop_index("ix_rule_lineage_current", table_name="rule_lineage", schema=SCHEMA)
    op.drop_index("ix_rule_lineage_identity", table_name="rule_lineage", schema=SCHEMA)
    op.drop_table("rule_lineage", schema=SCHEMA)
    op.drop_column("mining_runs", "sample_end", schema=SCHEMA)
    op.drop_column("mining_runs", "sample_start", schema=SCHEMA)
    op.drop_column("mining_runs", "batch_ids", schema=SCHEMA)
    op.drop_index("ix_order_baskets_batch_id", table_name="order_baskets", schema=SCHEMA)
    op.drop_column("order_baskets", "batch_id", schema=SCHEMA)
    op.drop_index("ix_basket_batches_fingerprint", table_name="basket_batches", schema=SCHEMA)
    op.drop_index("ix_basket_batches_code", table_name="basket_batches", schema=SCHEMA)
    op.drop_table("basket_batches", schema=SCHEMA)
