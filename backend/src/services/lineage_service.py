"""规则血缘服务：新批次挖掘完成后，按规则组合连接上一批次，继承复核结论与理由。

关键边界：
  - 只做「追溯」不做「改挂」：新批次生成全新的 RuleCandidate，PlanogramSlot 永远引用当批规则；
    基线已发布工单的 rule_id 保持不变。
  - 基线选择：同一 batch 序列里、当前批次之前最近一个成功批次（全量批次排在批次化批次之前）。
  - 消失的组合不建血缘（基线有、当前没有），它只出现在批次对比结果里，且不会进入新陈列建议。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.constants.enums import RuleStatus, SlotStatus
from src.models.planogram_slot import PlanogramSlot
from src.models.rule_candidate import RuleCandidate
from src.models.rule_lineage import RuleLineage
from src.models.rule_review import RuleReview
from src.models.user import User
from src.services import diff_core
from src.utils.logger import get_logger

logger = get_logger("basketrule.lineage")


def _latest_review(db: Session, rule_id) -> RuleReview | None:
    return db.execute(
        select(RuleReview)
        .where(RuleReview.rule_id == rule_id)
        .order_by(RuleReview.reviewed_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _published_rule_ids(db: Session, run_id) -> set:
    rows = db.execute(
        select(PlanogramSlot.rule_id)
        .join(RuleCandidate, RuleCandidate.id == PlanogramSlot.rule_id)
        .where(RuleCandidate.run_id == run_id, PlanogramSlot.status == SlotStatus.PUBLISHED.value)
    ).scalars().all()
    return set(rows)


def build_lineage(db: Session, current_run: MiningRun) -> int:
    """为当前批次的每条规则匹配基线规则并落血缘；返回写入条数。"""
    current_rules = list(
        db.execute(select(RuleCandidate).where(RuleCandidate.run_id == current_run.id)).scalars()
    )
    if not current_rules:
        return 0

    baseline_run = _pick_baseline_run(db, current_run)
    if baseline_run is None or baseline_run.id == current_run.id:
        return 0

    baseline_rules = list(
        db.execute(select(RuleCandidate).where(RuleCandidate.run_id == baseline_run.id)).scalars()
    )
    baseline_index = {
        diff_core.rule_identity_of(row.rule_key): row for row in baseline_rules
    }
    published_ids = _published_rule_ids(db, baseline_run.id)

    written = 0
    for current in current_rules:
        identity = diff_core.rule_identity_of(current.rule_key)
        baseline = baseline_index.get(identity)
        if baseline is None:
            continue  # 新增组合无基线可连
        review = _latest_review(db, baseline.id)
        reviewer_name = ""
        if review is not None:
            reviewer = db.get(User, review.reviewer_id)
            reviewer_name = reviewer.display_name if reviewer else ""
        change_type = diff_core.classify_change(
            {"lift": float(baseline.lift)}, {"lift": float(current.lift)}
        )
        db.add(
            RuleLineage(
                rule_identity=identity,
                baseline_run_id=baseline_run.id,
                current_run_id=current_run.id,
                baseline_rule_id=baseline.id,
                current_rule_id=current.id,
                change_type=change_type,
                baseline_status=baseline.status
                if baseline.status != RuleStatus.CANDIDATE.value
                else None,
                baseline_reason=review.reason if review else None,
                baseline_reviewer=reviewer_name,
                baseline_reviewed_at=review.reviewed_at if review else None,
                in_published_plan=baseline.id in published_ids,
            )
        )
        written += 1
    db.flush()
    logger.info(
        "lineage built: run=%s baseline=%s linked=%s/%s",
        current_run.run_label,
        baseline_run.run_label,
        written,
        len(current_rules),
    )
    return written


def _pick_baseline_run(db: Session, current_run: MiningRun):
    """基线批次：当前批次之前最近一个成功批次（按创建时间倒序取第一条）。"""
    from src.constants.enums import RunStatus

    return db.execute(
        select(MiningRun)
        .where(
            MiningRun.status == RunStatus.SUCCEEDED.value,
            MiningRun.created_at < current_run.created_at,
            MiningRun.id != current_run.id,
        )
        .order_by(MiningRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def lineage_for_rule(db: Session, rule_id) -> RuleLineage | None:
    """取某条（当前批次）规则的血缘记录，供规则详情展示原复核结论。"""
    return db.execute(
        select(RuleLineage)
        .where(RuleLineage.current_rule_id == rule_id)
        .order_by(RuleLineage.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


# 避免循环导入：模块顶部只在注解里用 MiningRun
from src.models.mining_run import MiningRun  # noqa: E402
