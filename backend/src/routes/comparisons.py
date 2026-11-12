from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.controllers import comparison_controller
from src.middlewares.rbac import require_permission
from src.models.user import User
from src.schemas.batch import ComparisonRequest

router = APIRouter(tags=["batch-comparison"])


@router.get("/comparisons/baselines")
def baselines(
    db: Session = Depends(get_db),
    _=Depends(require_permission("mining:read")),
) -> dict:
    """可作基线的已发布批次（存在已发布陈列工单的成功批次）。"""
    return comparison_controller.baselines(db)


@router.get("/comparisons")
def list_comparisons(
    db: Session = Depends(get_db),
    _=Depends(require_permission("mining:read")),
) -> dict:
    return comparison_controller.list_comparisons(db)


@router.post("/comparisons")
def compare(
    payload: ComparisonRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("mining:read")),
) -> dict:
    """两批次差异对比；首次计算落快照，之后同对批次直接复用（可复现）。"""
    return comparison_controller.compare(
        db, user, payload, trace_id=getattr(request.state, "trace_id", "")
    )
