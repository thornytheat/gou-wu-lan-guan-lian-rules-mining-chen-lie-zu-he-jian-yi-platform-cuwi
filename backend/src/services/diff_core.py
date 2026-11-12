"""周度批次对比的纯函数口径：规则身份归一、变化分类、受影响货架位计算。

不 import Session、不碰数据库，全部输入都是普通 dict / list，便于单元测试直接卡住口径。

变化分类（同一规则组合 rule_identity 跨两个批次比较）：
  new      新批次出现、基线没有
  gone     基线有、新批次消失（跌出支持度或过滤阈值）
  stronger 两批都在，lift 相对增幅 > LIFT_CHANGE_EPSILON
  weaker   两批都在，lift 相对降幅 > LIFT_CHANGE_EPSILON
  stable   两批都在，lift 相对变化在阈值内（含恰好等于阈值，不强行归入增强/减弱）

主口径指标是 lift；support / confidence / 共现小票数 / 预估月增量同时给出前后值与差值，
前端可展开查看，但分类结论只由 lift 决定，避免多口径互相打架。
"""
from __future__ import annotations

from src.constants.enums import RuleChangeType

# lift 相对变化阈值：|new-old|/old 超过 5% 才算增强/减弱，否则记持平
LIFT_CHANGE_EPSILON = 0.05


def rule_identity_of(rule_key: str) -> str:
    """剥离批次前缀：'RUN-2026-W45@N01>N02' → 'N01>N02'。"""
    return rule_key.split("@")[-1]


def lift_change_ratio(old_lift: float, new_lift: float) -> float:
    """相对变化率；基线 lift 非正时（理论上不会出现，防御）按 0 处理，不产生 inf。"""
    if old_lift <= 0:
        return 0.0
    return (new_lift - old_lift) / old_lift


def classify_change(old_rule: dict | None, new_rule: dict | None) -> str:
    """按两条规则记录的有无与 lift 变化给出变化类型。"""
    if old_rule is None and new_rule is not None:
        return RuleChangeType.NEW.value
    if old_rule is not None and new_rule is None:
        return RuleChangeType.GONE.value
    if old_rule is None or new_rule is None:  # pragma: no cover - 两边都空属于调用方错误
        return RuleChangeType.STABLE.value
    ratio = lift_change_ratio(float(old_rule["lift"]), float(new_rule["lift"]))
    if ratio > LIFT_CHANGE_EPSILON:
        return RuleChangeType.STRONGER.value
    if ratio < -LIFT_CHANGE_EPSILON:
        return RuleChangeType.WEAKER.value
    return RuleChangeType.STABLE.value


def _metric_block(rule: dict | None) -> dict:
    if rule is None:
        return {
            "lift": None,
            "support": None,
            "confidence": None,
            "cooccur_count": None,
            "uplift_month": None,
            "stable": None,
            "status": None,
        }
    return {
        "lift": float(rule["lift"]),
        "support": float(rule["support"]),
        "confidence": float(rule["confidence"]),
        "cooccur_count": int(rule["cooccur_count"]),
        "uplift_month": float(rule["uplift_month"]),
        "stable": bool(rule.get("stable")),
        "status": rule.get("status"),
    }


def _delta(new_value: float | None, old_value: float | None) -> float | None:
    if new_value is None or old_value is None:
        return None
    return round(new_value - old_value, 6)


def diff_rules(
    baseline_rules: list[dict],
    current_rules: list[dict],
) -> list[dict]:
    """两个批次的规则快照 → 全量差异行（new/gone/stronger/weaker/stable）。

    入参每条规则至少包含：rule_key / lift / support / confidence / cooccur_count /
    uplift_month / stable / status，可选 antecedent / consequent / labels。
    输出按「变化类型优先级 + lift 变化绝对值」排序，让运营最该处理的行排在最前。
    """
    baseline_index = {rule_identity_of(row["rule_key"]): row for row in baseline_rules}
    current_index = {rule_identity_of(row["rule_key"]): row for row in current_rules}
    identities = sorted(set(baseline_index) | set(current_index))

    changes: list[dict] = []
    for identity in identities:
        old = baseline_index.get(identity)
        new = current_index.get(identity)
        change_type = classify_change(old, new)
        old_metrics = _metric_block(old)
        new_metrics = _metric_block(new)
        anchor = new or old
        changes.append(
            {
                "rule_identity": identity,
                "change_type": change_type,
                "antecedent": anchor.get("antecedent", []),
                "consequent": anchor.get("consequent", []),
                "label": anchor.get("label", identity),
                "baseline_rule_id": old.get("id") if old else None,
                "current_rule_id": new.get("id") if new else None,
                "baseline": old_metrics,
                "current": new_metrics,
                "lift_delta": _delta(new_metrics["lift"], old_metrics["lift"]),
                "lift_change_ratio": round(
                    lift_change_ratio(old_metrics["lift"], new_metrics["lift"]), 6
                )
                if old_metrics["lift"] is not None and new_metrics["lift"] is not None
                else None,
                "cooccur_delta": _delta(
                    new_metrics["cooccur_count"], old_metrics["cooccur_count"]
                ),
                "uplift_delta": _delta(new_metrics["uplift_month"], old_metrics["uplift_month"]),
            }
        )

    order = {
        RuleChangeType.GONE.value: 0,
        RuleChangeType.WEAKER.value: 1,
        RuleChangeType.NEW.value: 2,
        RuleChangeType.STRONGER.value: 3,
        RuleChangeType.STABLE.value: 4,
    }
    changes.sort(
        key=lambda row: (
            order[row["change_type"]],
            -(abs(row["lift_delta"]) if row["lift_delta"] is not None else 0.0),
            row["rule_identity"],
        )
    )
    return changes


def summarize_changes(changes: list[dict]) -> dict[str, int]:
    """五类变化的计数（前端头部 KPI 直接消费）。"""
    counts = {item.value: 0 for item in RuleChangeType}
    for row in changes:
        counts[row["change_type"]] += 1
    return counts


def affected_published_slots(changes: list[dict], baseline_slots: list[dict]) -> list[dict]:
    """受影响货架位：基线已发布工单里，规则已消失或减弱的货架位（减弱/消失才会动摇现行陈列）。

    baseline_slots 每条至少：slot_key / plan_code / shelf_label / zone / status /
    rule_identity / rule_label / est_uplift。只统计 published 状态，
    草稿位不属于「已发布工单」，不在复现口径内。
    """
    risky = {
        row["rule_identity"]: row
        for row in changes
        if row["change_type"] in (RuleChangeType.GONE.value, RuleChangeType.WEAKER.value)
    }
    out: list[dict] = []
    for slot in baseline_slots:
        if slot.get("status") != "published":
            continue
        identity = slot.get("rule_identity")
        if identity not in risky:
            continue
        change = risky[identity]
        out.append(
            {
                "slot_key": slot["slot_key"],
                "plan_code": slot["plan_code"],
                "shelf_label": slot["shelf_label"],
                "zone": slot.get("zone", ""),
                "rule_identity": identity,
                "rule_label": slot.get("rule_label", identity),
                "change_type": change["change_type"],
                "baseline_lift": change["baseline"]["lift"],
                "current_lift": change["current"]["lift"],
                "lift_delta": change["lift_delta"],
                "est_uplift": float(slot.get("est_uplift", 0.0)),
            }
        )
    out.sort(key=lambda row: (row["plan_code"], row["slot_key"]))
    return out


def comparison_key(baseline_run_id: str, current_run_id: str) -> str:
    """对比快照自然键：同一对批次永远命中同一份快照（可复现的基础）。"""
    return f"{baseline_run_id}>{current_run_id}"
