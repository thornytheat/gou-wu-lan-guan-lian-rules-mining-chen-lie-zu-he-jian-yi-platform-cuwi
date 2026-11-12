"""规则血缘：跨批次按「规则组合」（剥离批次前缀后的 identity）连接同一组合的候选记录。

保留的规则（新批次仍有同一组合）通过本表把基线批次的复核结论与理由带到新批次，
但新批次的 PlanogramSlot 仍然挂在新规则记录上——已发布工单不被改挂。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.config.settings import settings
from src.models.base import Base, TimestampMixin, new_uuid, utcnow


class RuleLineage(Base, TimestampMixin):
    __tablename__ = "rule_lineage"
    __table_args__ = {"schema": settings.db_schema}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    # 规则组合自然键，如 "N01>N02"（去掉 "RUN-xxx@" 前缀），跨批次据此匹配
    rule_identity: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    baseline_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{settings.db_schema}.mining_runs.id"), nullable=False, index=True
    )
    current_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{settings.db_schema}.mining_runs.id"), nullable=False, index=True
    )
    baseline_rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{settings.db_schema}.rule_candidates.id"), nullable=False
    )
    current_rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{settings.db_schema}.rule_candidates.id"), nullable=False, index=True
    )
    change_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # 基线规则最新一次复核结论快照（adopt / reject / park / None）
    baseline_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    baseline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    baseline_reviewer: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    baseline_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 该组合是否在基线批次进入过（含已发布）陈列工单——影响新批次陈列建议的提示
    in_published_plan: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
