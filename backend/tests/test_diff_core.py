"""周度批次对比口径：规则身份归一、五类变化分类、受影响货架位、可复现快照键。"""
from __future__ import annotations

import pytest

from src.constants.enums import RuleChangeType
from src.services.diff_core import (
    affected_published_slots,
    classify_change,
    comparison_key,
    diff_rules,
    lift_change_ratio,
    rule_identity_of,
    summarize_changes,
)


def _rule(rule_key: str, lift: float, *, support: float = 0.02, confidence: float = 0.4,
          cooccur: int = 40, uplift: float = 2000.0, stable: bool = True,
          status: str = "candidate", rule_id: str | None = None) -> dict:
    return {
        "id": rule_id or f"id-{rule_key}",
        "rule_key": rule_key,
        "antecedent": [rule_key.split(">")[0]],
        "consequent": [rule_key.split(">")[1]],
        "label": rule_key,
        "lift": lift,
        "support": support,
        "confidence": confidence,
        "cooccur_count": cooccur,
        "uplift_month": uplift,
        "stable": stable,
        "status": status,
    }


# ----------------------------------------------------------- 身份归一 / 变化率


def test_rule_identity_strips_run_prefix() -> None:
    assert rule_identity_of("RUN-2026-W45@N01>N02") == "N01>N02"
    assert rule_identity_of("N04>N05") == "N04>N05"


def test_lift_change_ratio_basic_and_guard() -> None:
    assert lift_change_ratio(2.0, 2.2) == pytest.approx(0.1)
    assert lift_change_ratio(0.0, 1.5) == 0.0  # 防御：不产生 inf


# ----------------------------------------------------------- 五类分类


def test_classify_new_gone_and_stable() -> None:
    old = _rule("A>B", 1.5)
    new = _rule("A>B", 1.51)
    assert classify_change(old, new) == RuleChangeType.STABLE.value
    assert classify_change(None, new) == RuleChangeType.NEW.value
    assert classify_change(old, None) == RuleChangeType.GONE.value


def test_classify_stronger_weakener_threshold_is_exclusive() -> None:
    old = _rule("A>B", 2.0)
    # 恰在阈值内侧（4.99% 变化）→ 持平，证明必须严格超过 5% 才算增强/减弱
    just_inside_up = _rule("A>B", 2.0 * 1.0499)
    assert classify_change(old, just_inside_up) == RuleChangeType.STABLE.value
    # 超过 5% → 增强
    stronger = _rule("A>B", 2.11)
    assert classify_change(old, stronger) == RuleChangeType.STRONGER.value
    # 低于 -5% → 减弱
    weaker = _rule("A>B", 1.89)
    assert classify_change(old, weaker) == RuleChangeType.WEAKER.value
    # 阈值内侧向下（-4.99%）→ 持平
    just_inside_down = _rule("A>B", 2.0 * 0.9501)
    assert classify_change(old, just_inside_down) == RuleChangeType.STABLE.value


# ----------------------------------------------------------- 全量 diff


def _two_batches() -> tuple[list[dict], list[dict]]:
    baseline = [
        _rule("RUN-W45@KEEP>S", 1.50, rule_id="b-keep"),       # 持平
        _rule("RUN-W45@UP>S", 1.50, rule_id="b-up"),           # 增强
        _rule("RUN-W45@DOWN>S", 2.00, rule_id="b-down"),       # 减弱
        _rule("RUN-W45@GONE>S", 1.80, rule_id="b-gone"),       # 消失
    ]
    current = [
        _rule("RUN-W46@KEEP>S", 1.52, rule_id="c-keep"),
        _rule("RUN-W46@UP>S", 1.70, rule_id="c-up"),
        _rule("RUN-W46@DOWN>S", 1.70, rule_id="c-down"),
        _rule("RUN-W46@NEW>S", 1.90, rule_id="c-new"),         # 新增
    ]
    return baseline, current


def test_diff_rules_covers_all_five_change_types() -> None:
    baseline, current = _two_batches()
    changes = diff_rules(baseline, current)
    by_identity = {row["rule_identity"]: row for row in changes}

    assert set(by_identity) == {"KEEP>S", "UP>S", "DOWN>S", "GONE>S", "NEW>S"}
    assert by_identity["KEEP>S"]["change_type"] == RuleChangeType.STABLE.value
    assert by_identity["UP>S"]["change_type"] == RuleChangeType.STRONGER.value
    assert by_identity["DOWN>S"]["change_type"] == RuleChangeType.WEAKER.value
    assert by_identity["GONE>S"]["change_type"] == RuleChangeType.GONE.value
    assert by_identity["NEW>S"]["change_type"] == RuleChangeType.NEW.value

    counts = summarize_changes(changes)
    assert counts == {"new": 1, "gone": 1, "stronger": 1, "weaker": 1, "stable": 1}


def test_diff_metrics_are_side_correct_and_gone_keeps_baseline() -> None:
    baseline, current = _two_batches()
    changes = diff_rules(baseline, current)
    by_identity = {row["rule_identity"]: row for row in changes}

    up = by_identity["UP>S"]
    assert up["baseline"]["lift"] == 1.50
    assert up["current"]["lift"] == 1.70
    assert up["lift_delta"] == pytest.approx(0.20)
    assert up["lift_change_ratio"] == pytest.approx(0.20 / 1.50, abs=1e-6)
    assert up["baseline_rule_id"] == "b-up"
    assert up["current_rule_id"] == "c-up"

    gone = by_identity["GONE>S"]
    assert gone["current"]["lift"] is None
    assert gone["baseline"]["lift"] == 1.80
    assert gone["current_rule_id"] is None
    assert gone["baseline_rule_id"] == "b-gone"

    new = by_identity["NEW>S"]
    assert new["baseline"]["lift"] is None
    assert new["current"]["lift"] == 1.90


def test_diff_ordering_puts_gone_and_weaker_first() -> None:
    baseline, current = _two_batches()
    changes = diff_rules(baseline, current)
    types = [row["change_type"] for row in changes]
    # 消失 → 减弱 → 新增 → 增强 → 持平 的优先级
    assert types == [
        RuleChangeType.GONE.value,
        RuleChangeType.WEAKER.value,
        RuleChangeType.NEW.value,
        RuleChangeType.STRONGER.value,
        RuleChangeType.STABLE.value,
    ]


def test_diff_is_deterministic_and_input_order_independent() -> None:
    import random

    baseline, current = _two_batches()
    first = diff_rules(baseline, current)
    shuffled_b = list(baseline)
    shuffled_c = list(current)
    random.Random(3).shuffle(shuffled_b)
    random.Random(5).shuffle(shuffled_c)
    assert diff_rules(shuffled_b, shuffled_c) == first


# ----------------------------------------------------------- 受影响货架位


def test_affected_published_slots_only_gone_and_weaker() -> None:
    baseline, current = _two_batches()
    changes = diff_rules(baseline, current)
    slots = [
        # 消失规则占用的已发布位
        {"slot_key": "PLAN-W45@GONE>S", "plan_code": "PLAN-W45", "shelf_label": "端架A 01",
         "zone": "端架A", "status": "published", "rule_identity": "GONE>S",
         "rule_label": "GONE>S", "est_uplift": 2400.0},
        # 减弱规则占用的已发布位
        {"slot_key": "PLAN-W45@DOWN>S", "plan_code": "PLAN-W45", "shelf_label": "H3 端头",
         "zone": "H3", "status": "published", "rule_identity": "DOWN>S",
         "rule_label": "DOWN>S", "est_uplift": 1800.0},
        # 增强规则也有位，但不该出现在受影响清单
        {"slot_key": "PLAN-W45@UP>S", "plan_code": "PLAN-W45", "shelf_label": "H4",
         "zone": "H4", "status": "published", "rule_identity": "UP>S",
         "rule_label": "UP>S", "est_uplift": 1600.0},
        # 消失规则的草稿位不算（非已发布工单）
        {"slot_key": "PLAN-DRAFT@GONE>S", "plan_code": "PLAN-DRAFT", "shelf_label": "草稿",
         "zone": "X", "status": "draft", "rule_identity": "GONE>S",
         "rule_label": "GONE>S", "est_uplift": 10.0},
    ]

    affected = affected_published_slots(changes, slots)

    assert [row["slot_key"] for row in affected] == ["PLAN-W45@DOWN>S", "PLAN-W45@GONE>S"]
    gone_slot = next(row for row in affected if row["rule_identity"] == "GONE>S")
    assert gone_slot["change_type"] == RuleChangeType.GONE.value
    assert gone_slot["current_lift"] is None
    weaker_slot = next(row for row in affected if row["rule_identity"] == "DOWN>S")
    assert weaker_slot["change_type"] == RuleChangeType.WEAKER.value
    assert weaker_slot["baseline_lift"] == 2.00


def test_comparison_key_is_stable_for_same_pair() -> None:
    key = comparison_key("run-b", "run-c")
    assert key == "run-b>run-c"
    # 同一对批次（无论请求多少次）键不变 → 命中同一快照
    assert comparison_key("run-b", "run-c") == key
    assert comparison_key("run-c", "run-b") != key
