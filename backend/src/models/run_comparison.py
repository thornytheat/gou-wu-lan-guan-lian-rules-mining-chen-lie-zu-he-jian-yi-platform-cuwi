"""批次对比快照：固定 (基线批次, 当前批次) 的差异结果，重复请求/重放得到同一份输出。

选择已发布批次作基线时，差异分类、指标变化与受影响货架位在首次计算时落快照；
之后无论规则复核状态怎么变，同一对批次的对比结果都可复现。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.config.settings import settings
from src.models.base import Base, TimestampMixin, new_uuid, utcnow


class RunComparison(Base, TimestampMixin):
    __tablename__ = "run_comparisons"
    __table_args__ = {"schema": settings.db_schema}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    comparison_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    baseline_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{settings.db_schema}.mining_runs.id"), nullable=False, index=True
    )
    current_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{settings.db_schema}.mining_runs.id"), nullable=False, index=True
    )
    # 变化分类计数（new/gone/stronger/weaker/stable）
    counts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # 两批样本小票数与时间范围等头部信息
    baseline_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    current_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # 全量差异行（含指标前后值、复核追溯、受影响货架位）
    changes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    affected_slots: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
