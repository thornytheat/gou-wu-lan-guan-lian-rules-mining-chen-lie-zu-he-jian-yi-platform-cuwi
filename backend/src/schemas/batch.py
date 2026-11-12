"""小票批次导入 / 批次对比请求模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class BasketBatchImportRequest(BaseModel):
    batch_code: str = Field(min_length=2, max_length=60)
    note: str = Field(default="", max_length=500)
    imported_filename: str | None = Field(default=None, max_length=200)
    baskets: list[dict] = Field(min_length=1, max_length=20000)


class ComparisonRequest(BaseModel):
    baseline_run_id: str = Field(min_length=8)
    current_run_id: str = Field(min_length=8)
    # 默认走快照；显式 force_refresh 才允许重算（重算结果仍按同键覆盖，保证可复现）
    force_refresh: bool = False
