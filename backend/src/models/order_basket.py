"""小票与明细行（一行一小票；lines 里是明细行 JSON 数组）。"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.config.settings import settings
from src.models.base import Base, TimestampMixin, new_uuid


class OrderBasket(Base, TimestampMixin):
    __tablename__ = "order_baskets"
    __table_args__ = {"schema": settings.db_schema}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    basket_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    # 所属小票批次（每周补入独立建档；seed 数据挂 W45 批次）
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{settings.db_schema}.basket_batches.id"),
        nullable=True,
        index=True,
    )
    store_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    store_name: Mapped[str] = mapped_column(String(80), nullable=False)
    store_tier: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    basket_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    lines: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
