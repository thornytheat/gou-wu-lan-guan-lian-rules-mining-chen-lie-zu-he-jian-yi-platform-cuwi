"""小票批次建档与周度补入：内容指纹去重，同一批小票重复导入只生效一次。

幂等口径：
  对规范化后的小票内容（basket_no + 排序后 lines + basket_ts，与导入顺序无关）计算 sha256；
  content_fingerprint 唯一，命中已存在批次时原样返回并标记 inserted=0，不产生任何重复小票，
  因此「重复运行同一批小票」时挖掘输入完全一致，结果只生效一次、可复现。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.constants import error_codes as codes
from src.constants.enums import BatchSource
from src.models.basket_batch import BasketBatch
from src.models.order_basket import OrderBasket
from src.models.user import User
from src.utils.errors import AppError
from src.utils.logger import get_logger

logger = get_logger("basketrule.batches")


def _fingerprint(baskets: list[dict]) -> str:
    """规范化内容指纹：按 basket_no 排序、行内按 sku 排序，导入顺序不影响指纹。"""
    normalized = []
    for basket in sorted(baskets, key=lambda item: item["basket_no"]):
        lines = sorted(
            (
                {
                    "sku": str(line["sku"]),
                    "qty": int(line["qty"]),
                    "amount": str(line["amount"]),
                }
                for line in basket["lines"]
            ),
            key=lambda line: line["sku"],
        )
        normalized.append(
            {
                "basket_no": basket["basket_no"],
                "store_code": basket["store_code"],
                "store_tier": basket["store_tier"],
                "channel": basket["channel"],
                "basket_ts": _iso(basket["basket_ts"]),
                "net_amount": str(basket["net_amount"]),
                "item_count": int(basket["item_count"]),
                "lines": lines,
            }
        )
    blob = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _iso(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _parse_ts(value) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise AppError(codes.VALIDATION_ERROR, "小票时间必须带时区", f"basket_ts={value}")
        return value
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise AppError(codes.VALIDATION_ERROR, "小票时间必须带时区", f"basket_ts={value}")
    return parsed


def validate_baskets(baskets: list[dict]) -> None:
    if not baskets:
        raise AppError(codes.VALIDATION_ERROR, "小票批次为空，无法导入", "baskets empty")
    seen: set[str] = set()
    for index, basket in enumerate(baskets):
        missing = [
            key
            for key in ("basket_no", "store_code", "store_name", "store_tier", "channel", "basket_ts", "lines")
            if key not in basket
        ]
        if missing:
            raise AppError(
                codes.VALIDATION_ERROR,
                f"第 {index + 1} 张小票缺字段：{','.join(missing)}",
                f"basket_no={basket.get('basket_no')}",
            )
        if basket["basket_no"] in seen:
            raise AppError(
                codes.VALIDATION_ERROR,
                "批次内小票号重复",
                f"basket_no={basket['basket_no']}",
            )
        seen.add(basket["basket_no"])
        if not basket["lines"]:
            raise AppError(
                codes.VALIDATION_ERROR,
                f"小票 {basket['basket_no']} 没有明细行",
                "lines empty",
            )
        _parse_ts(basket["basket_ts"])


def import_batch(
    db: Session,
    user: User,
    batch_code: str,
    baskets: list[dict],
    source: str = BatchSource.IMPORT.value,
    imported_filename: str | None = None,
    note: str = "",
    trace_id: str = "",
) -> tuple[BasketBatch, bool]:
    """导入一批小票并建档；指纹命中时短路返回 (已有批次, False)。"""
    validate_baskets(baskets)
    fingerprint = _fingerprint(baskets)

    existing = db.execute(
        select(BasketBatch).where(BasketBatch.content_fingerprint == fingerprint)
    ).scalar_one_or_none()
    if existing is not None:
        logger.info("batch fingerprint hit, skip import: %s", existing.batch_code)
        return existing, False

    if db.execute(select(BasketBatch).where(BasketBatch.batch_code == batch_code)).first():
        raise AppError(codes.CONFLICT, "批次编号已存在", f"batch_code={batch_code}")

    timestamps = [_parse_ts(item["basket_ts"]) for item in baskets]
    period_start, period_end = min(timestamps), max(timestamps)

    # 与库内已有小票号冲突也要拒绝（自然键唯一，提前报错而不是等数据库约束）
    incoming_nos = {item["basket_no"] for item in baskets}
    conflict = db.execute(
        select(OrderBasket.basket_no).where(OrderBasket.basket_no.in_(incoming_nos)).limit(1)
    ).first()
    if conflict:
        raise AppError(codes.CONFLICT, "小票号与已入库小票冲突", f"basket_no={conflict[0]}")

    batch = BasketBatch(
        batch_code=batch_code,
        source=source,
        period_start=period_start,
        period_end=period_end,
        basket_count=len(baskets),
        content_fingerprint=fingerprint,
        imported_filename=imported_filename,
        note=note,
        imported_by=user.id if user else None,
    )
    db.add(batch)
    db.flush()

    for item in baskets:
        db.add(
            OrderBasket(
                basket_no=item["basket_no"],
                batch_id=batch.id,
                store_code=item["store_code"],
                store_name=item["store_name"],
                store_tier=item["store_tier"],
                channel=item["channel"],
                basket_ts=_parse_ts(item["basket_ts"]),
                net_amount=Decimal(str(item["net_amount"])),
                item_count=int(item["item_count"]),
                lines=item["lines"],
            )
        )
    db.flush()
    logger.info(
        "batch %s imported: baskets=%s range=%s~%s",
        batch_code,
        len(baskets),
        period_start.date(),
        period_end.date(),
    )
    return batch, True


def list_batches(db: Session) -> list[BasketBatch]:
    return list(
        db.execute(select(BasketBatch).order_by(BasketBatch.period_start.desc())).scalars().all()
    )


def get_batch(db: Session, batch_id: str) -> BasketBatch:
    batch = db.get(BasketBatch, batch_id)
    if batch is None:
        raise AppError(codes.NOT_FOUND, "小票批次不存在", f"batch_id={batch_id}")
    return batch


def resolve_batch_ids(db: Session, batch_ids: list[str] | None) -> list[str] | None:
    """校验前端传入的批次 id 全部存在；空列表/None → None 表示全量快照。"""
    if not batch_ids:
        return None
    rows = db.execute(select(BasketBatch.id).where(BasketBatch.id.in_(batch_ids))).scalars().all()
    found = {str(row) for row in rows}
    missing = [bid for bid in batch_ids if bid not in found]
    if missing:
        raise AppError(codes.NOT_FOUND, "小票批次不存在", f"batch_id={missing[0]}")
    return [str(row) for row in rows]


def serialize_batch(batch: BasketBatch, basket_total: int | None = None) -> dict:
    return {
        "id": str(batch.id),
        "batch_code": batch.batch_code,
        "source": batch.source,
        "period_start": batch.period_start.isoformat() if batch.period_start else None,
        "period_end": batch.period_end.isoformat() if batch.period_end else None,
        "basket_count": batch.basket_count if basket_total is None else basket_total,
        "imported_filename": batch.imported_filename,
        "note": batch.note,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
    }
