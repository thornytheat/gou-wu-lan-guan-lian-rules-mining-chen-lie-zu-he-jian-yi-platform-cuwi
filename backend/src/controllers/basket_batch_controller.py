"""小票批次：列表 / 详情 / 周度补入（指纹幂等）。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from src.constants.enums import BatchSource
from src.constants.log_templates import ACTION_BASKET_IMPORT
from src.models.user import User
from src.schemas.batch import BasketBatchImportRequest
from src.services import audit_service, basket_batch_service


def list_batches(db: Session) -> dict:
    batches = basket_batch_service.list_batches(db)
    items = [basket_batch_service.serialize_batch(batch) for batch in batches]
    return {"batches": items, "count": len(items)}


def get_batch(db: Session, batch_id: str) -> dict:
    batch = basket_batch_service.get_batch(db, batch_id)
    return basket_batch_service.serialize_batch(batch)


def import_batch(
    db: Session, user: User, payload: BasketBatchImportRequest, trace_id: str = ""
) -> dict:
    batch, inserted = basket_batch_service.import_batch(
        db,
        user=user,
        batch_code=payload.batch_code,
        baskets=payload.baskets,
        source=BatchSource.IMPORT.value,
        imported_filename=payload.imported_filename,
        note=payload.note,
        trace_id=trace_id,
    )
    if inserted:
        audit_service.record(
            db,
            action=ACTION_BASKET_IMPORT,
            actor=user,
            entity_type="basket_batch",
            entity_id=batch.id,
            detail={
                "batch_code": batch.batch_code,
                "basket_count": batch.basket_count,
                "period_start": batch.period_start.isoformat(),
                "period_end": batch.period_end.isoformat(),
            },
            trace_id=trace_id,
        )
        db.commit()
    return {
        "batch": basket_batch_service.serialize_batch(batch),
        "inserted": inserted,
        "message": "导入成功" if inserted else "相同内容的小票批次已存在，重复导入未生效",
    }
