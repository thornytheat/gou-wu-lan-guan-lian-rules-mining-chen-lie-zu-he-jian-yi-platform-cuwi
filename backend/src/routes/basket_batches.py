from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.controllers import basket_batch_controller
from src.middlewares.rbac import require_permission
from src.middlewares.rate_limit import rate_limit
from src.models.user import User
from src.schemas.batch import BasketBatchImportRequest

router = APIRouter(tags=["basket-batches"])


@router.get("/basket-batches")
def list_batches(
    db: Session = Depends(get_db),
    _=Depends(require_permission("mining:read")),
) -> dict:
    # 批次元数据（编号/票数/时间范围，不含 POS 明细行）对全部可看挖掘的角色开放
    return basket_batch_controller.list_batches(db)


@router.get("/basket-batches/{batch_id}")
def get_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    _=Depends(require_permission("mining:read")),
) -> dict:
    return basket_batch_controller.get_batch(db, batch_id)


@router.post("/basket-batches")
def import_batch(
    payload: BasketBatchImportRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("mining:run")),
    _=rate_limit("mining"),
) -> dict:
    """周度小票补入：内容指纹去重，同一批重复导入只生效一次（analyst/admin）。"""
    return basket_batch_controller.import_batch(
        db, user, payload, trace_id=getattr(request.state, "trace_id", "")
    )
