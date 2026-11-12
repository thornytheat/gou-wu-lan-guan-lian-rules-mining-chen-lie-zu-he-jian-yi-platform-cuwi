"""批次对比：差异快照计算 / 历史快照 / 已发布基线下拉。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from src.constants.log_templates import ACTION_BATCH_COMPARE
from src.models.user import User
from src.schemas.batch import ComparisonRequest
from src.services import audit_service, comparison_service


def compare(db: Session, user: User, payload: ComparisonRequest, trace_id: str = "") -> dict:
    result = comparison_service.compare_runs(
        db,
        baseline_run_id=payload.baseline_run_id,
        current_run_id=payload.current_run_id,
        use_cache=not payload.force_refresh,
    )
    if not result["reused_snapshot"]:
        audit_service.record(
            db,
            action=ACTION_BATCH_COMPARE,
            actor=user,
            entity_type="run_comparison",
            entity_id=result["comparison_key"],
            detail={"counts": result["counts"], "affected_slots": len(result["affected_slots"])},
            trace_id=trace_id,
        )
        db.commit()
    return result


def list_comparisons(db: Session) -> dict:
    items = comparison_service.list_comparisons(db)
    return {"comparisons": items, "count": len(items)}


def baselines(db: Session) -> dict:
    items = comparison_service.published_baseline_candidates(db)
    return {"baselines": items, "count": len(items)}
