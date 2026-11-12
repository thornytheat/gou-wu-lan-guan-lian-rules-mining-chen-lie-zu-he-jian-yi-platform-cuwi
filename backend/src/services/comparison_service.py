"""批次对比服务：两批次规则差异分类、复核追溯、受影响货架位，结果落快照保证可复现。

复现口径：
  对比结果按 (baseline_run_id, current_run_id) 存 RunComparison 快照；
  同一对批次再次请求直接返回快照——即使之后规则被重新复核、陈列工单状态变化，
  差异分类与受影响货架位都与首次计算逐字一致。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.constants import error_codes as codes
from src.constants.enums import RunStatus, SlotStatus
from src.models.planogram_slot import PlanogramSlot
from src.models.rule_candidate import RuleCandidate
from src.models.rule_lineage import RuleLineage
from src.models.run_comparison import RunComparison
from src.services import basket_service, diff_core, fixtures_loader
from src.utils.errors import AppError
from src.utils.logger import get_logger

logger = get_logger("basketrule.comparison")


def _get_succeeded_run(db: Session, run_id: str):
    from src.models.mining_run import MiningRun

    run = db.get(MiningRun, run_id)
    if run is None:
        raise AppError(codes.NOT_FOUND, "挖掘批次不存在", f"run_id={run_id}")
    if run.status != RunStatus.SUCCEEDED.value:
        raise AppError(codes.CONFLICT, "只能对比已完成的挖掘批次", f"run={run.run_label} status={run.status}")
    return run


def _rule_payload(db: Session, row: RuleCandidate) -> dict:
    names, _ = basket_service.sku_maps(db)
    return {
        "id": str(row.id),
        "rule_key": row.rule_key,
        "antecedent": row.antecedent,
        "consequent": row.consequent,
        "label": f"{' + '.join(names.get(code, code) for code in row.antecedent)} → "
        f"{' + '.join(names.get(code, code) for code in row.consequent)}",
        "support": float(row.support),
        "confidence": float(row.confidence),
        "lift": float(row.lift),
        "cooccur_count": row.cooccur_count,
        "uplift_month": float(row.uplift_month),
        "stable": row.stable,
        "status": row.status,
    }


def _run_snapshot(run) -> dict:
    return {
        "run_id": str(run.id),
        "run_label": run.run_label,
        "basket_count": run.basket_count,
        "sample_start": run.sample_start.isoformat() if run.sample_start else None,
        "sample_end": run.sample_end.isoformat() if run.sample_end else None,
        "batch_ids": [str(bid) for bid in (run.batch_ids or [])],
        "passed_rules": run.passed_rules,
        "stable_rules": run.stable_rules,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def _baseline_slots(db: Session, baseline_run) -> list[dict]:
    rows = list(
        db.execute(
            select(PlanogramSlot, RuleCandidate)
            .join(RuleCandidate, RuleCandidate.id == PlanogramSlot.rule_id)
            .where(RuleCandidate.run_id == baseline_run.id)
        ).all()
    )
    names, _ = basket_service.sku_maps(db)
    out: list[dict] = []
    for slot, rule in rows:
        label = f"{' + '.join(names.get(code, code) for code in rule.antecedent)} → " \
                f"{' + '.join(names.get(code, code) for code in rule.consequent)}"
        out.append(
            {
                "slot_key": slot.slot_key,
                "plan_code": slot.plan_code,
                "shelf_label": slot.shelf_label,
                "zone": slot.zone,
                "status": slot.status,
                "est_uplift": float(slot.est_uplift),
                "rule_identity": diff_core.rule_identity_of(rule.rule_key),
                "rule_label": label,
            }
        )
    return out


def _lineage_map(db: Session, current_run_id) -> dict[str, RuleLineage]:
    rows = db.execute(
        select(RuleLineage).where(RuleLineage.current_run_id == current_run_id)
    ).scalars().all()
    return {row.rule_identity: row for row in rows}


def compare_runs(
    db: Session,
    baseline_run_id: str,
    current_run_id: str,
    use_cache: bool = True,
) -> dict:
    baseline = _get_succeeded_run(db, baseline_run_id)
    current = _get_succeeded_run(db, current_run_id)
    if baseline.id == current.id:
        raise AppError(codes.VALIDATION_ERROR, "请选择两个不同的批次进行对比", "same run")

    key = diff_core.comparison_key(str(baseline.id), str(current.id))
    if use_cache:
        cached = db.execute(
            select(RunComparison).where(RunComparison.comparison_key == key)
        ).scalar_one_or_none()
        if cached is not None:
            return _serialize(cached, reused=True)

    baseline_rules = [
        _rule_payload(db, row)
        for row in db.execute(
            select(RuleCandidate).where(RuleCandidate.run_id == baseline.id)
        ).scalars()
    ]
    current_rules = [
        _rule_payload(db, row)
        for row in db.execute(
            select(RuleCandidate).where(RuleCandidate.run_id == current.id)
        ).scalars()
    ]

    changes = diff_core.diff_rules(baseline_rules, current_rules)
    lineage = _lineage_map(db, current.id)
    for row in changes:
        link = lineage.get(row["rule_identity"])
        row["lineage"] = (
            None
            if link is None
            else {
                "baseline_status": link.baseline_status,
                "baseline_reason": link.baseline_reason,
                "baseline_reviewer": link.baseline_reviewer,
                "baseline_reviewed_at": link.baseline_reviewed_at.isoformat()
                if link.baseline_reviewed_at
                else None,
                "in_published_plan": link.in_published_plan,
            }
        )
        # 货架元数据（消失规则也要能指出它原来占的是哪个货架区）
        meta = fixtures_loader.zone_payload(row["rule_identity"])
        row["zone"] = meta.get("zone", "")
        row["shelf_label"] = meta.get("shelf_label", "")
        row["conflict_group"] = meta.get("zone_code", "")

    affected = diff_core.affected_published_slots(changes, _baseline_slots(db, baseline))
    counts = diff_core.summarize_changes(changes)

    snapshot = db.execute(
        select(RunComparison).where(RunComparison.comparison_key == key)
    ).scalar_one_or_none()
    if snapshot is None:
        snapshot = RunComparison(
            comparison_key=key,
            baseline_run_id=baseline.id,
            current_run_id=current.id,
        )
        db.add(snapshot)
    # force_refresh 时覆盖同键快照内容，comparison_key 不变，差异结果仍按同一对批次复现
    snapshot.counts = counts
    snapshot.baseline_snapshot = _run_snapshot(baseline)
    snapshot.current_snapshot = _run_snapshot(current)
    snapshot.changes = changes
    snapshot.affected_slots = affected
    db.commit()
    logger.info("comparison snapshot stored: %s counts=%s", key, counts)
    return _serialize(snapshot, reused=False)


def _serialize(snapshot: RunComparison, reused: bool) -> dict:
    return {
        "comparison_key": snapshot.comparison_key,
        "reused_snapshot": reused,
        "counts": snapshot.counts,
        "baseline": snapshot.baseline_snapshot,
        "current": snapshot.current_snapshot,
        "changes": snapshot.changes,
        "affected_slots": snapshot.affected_slots,
        "snapshot_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
    }


def list_comparisons(db: Session) -> list[dict]:
    rows = db.execute(
        select(RunComparison).order_by(RunComparison.created_at.desc())
    ).scalars().all()
    return [
        {
            "comparison_key": row.comparison_key,
            "counts": row.counts,
            "baseline": row.baseline_snapshot,
            "current": row.current_snapshot,
            "snapshot_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


def published_baseline_candidates(db: Session) -> list[dict]:
    """可作基线的已发布批次：存在 published 建议位的成功批次（前端基线下拉）。"""
    from src.models.mining_run import MiningRun

    run_ids = (
        db.execute(
            select(RuleCandidate.run_id)
            .join(PlanogramSlot, PlanogramSlot.rule_id == RuleCandidate.id)
            .where(PlanogramSlot.status == SlotStatus.PUBLISHED.value)
            .group_by(RuleCandidate.run_id)
        )
        .scalars()
        .all()
    )
    if not run_ids:
        return []
    runs = list(
        db.execute(
            select(MiningRun)
            .where(MiningRun.id.in_(run_ids), MiningRun.status == RunStatus.SUCCEEDED.value)
            .order_by(MiningRun.created_at.desc())
        ).scalars()
    )
    return [_run_snapshot(run) for run in runs]
