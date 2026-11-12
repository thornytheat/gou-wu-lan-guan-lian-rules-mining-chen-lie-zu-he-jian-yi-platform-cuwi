"""小票批次：每周补入的一批小票独立建档，内容指纹保证重复导入只生效一次。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.config.settings import settings
from src.models.base import Base, TimestampMixin, new_uuid, utcnow


class BasketBatch(Base, TimestampMixin):
    __tablename__ = "basket_batches"
    __table_args__ = {"schema": settings.db_schema}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    batch_code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="import", index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    basket_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 规范化小票内容的 sha256：同一批文件重复导入时据此短路，保证「重复运行同一批小票只生效一次」
    content_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    imported_filename: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    imported_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{settings.db_schema}.users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
