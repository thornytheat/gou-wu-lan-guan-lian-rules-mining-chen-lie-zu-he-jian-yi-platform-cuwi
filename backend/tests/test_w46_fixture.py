"""W46 周度小票：确定性 + 相对 W45 的五类变化契约（新增/消失/增强/减弱/持平）。

这是周度批次对比演示的数据底座：任何对生成器或算法口径的意外漂移都会让契约失败。
"""
from __future__ import annotations

from src.services import apriori_service
from src.services.diff_core import diff_rules, summarize_changes
from src.services.mining_core import filter_rules
from scripts.fixtures_baskets import build_baskets, transactions
from scripts.fixtures_baskets_w46 import (
    W46_BASKET_TOTAL,
    W46_EXPECTED_CHANGES,
    W46_SAMPLE_DAYS,
    W46_SAMPLE_START,
    build_w46_baskets,
)


def _passed(baskets: list[dict], prefix: str) -> list[dict]:
    tx = transactions(baskets)
    result = apriori_service.apriori([t for t, _ in tx], min_support=0.01, max_itemset=3)
    rules = apriori_service.build_rules(result["counts"], result["basket_count"], 0.05)
    return [
        {
            "id": f"{prefix}-{rule['rule_key']}",
            "rule_key": f"{prefix}@{rule['rule_key']}",
            "lift": rule["lift"],
            "support": rule["support"],
            "confidence": rule["confidence"],
            "cooccur_count": rule["cooccur_count"],
            "uplift_month": rule["cooccur_count"] * 40 * 0.35 * 30 / 7,
            "stable": True,
            "status": "candidate",
        }
        for rule in filter_rules(rules, 1.2, 0.25)
    ]


def test_w46_is_deterministic_and_well_formed() -> None:
    first = build_w46_baskets()
    second = build_w46_baskets()
    assert first == second  # 同进程重复生成逐字一致
    assert len(first) == W46_BASKET_TOTAL == 3000
    nos = [basket["basket_no"] for basket in first]
    assert len(set(nos)) == len(nos)  # 小票号唯一
    assert all(no.startswith("BR-W46-") for no in nos)
    days = {basket["basket_ts"].date().isoformat() for basket in first}
    assert min(days) == W46_SAMPLE_START
    assert len(days) == W46_SAMPLE_DAYS
    # 与 W45 小票号不冲突（两批可同时入库）
    w45_nos = {basket["basket_no"] for basket in build_baskets()}
    assert not (set(nos) & w45_nos)


def test_w46_vs_w45_produces_all_five_change_types() -> None:
    changes = diff_rules(_passed(build_baskets(), "W45"), _passed(build_w46_baskets(), "W46"))
    grouped: dict[str, list[str]] = {}
    for row in changes:
        grouped.setdefault(row["change_type"], []).append(row["rule_identity"])

    assert grouped["new"] == W46_EXPECTED_CHANGES["new"]
    assert grouped["gone"] == W46_EXPECTED_CHANGES["gone"]
    assert grouped["stronger"] == W46_EXPECTED_CHANGES["stronger"]
    assert grouped["weaker"] == W46_EXPECTED_CHANGES["weaker"]
    assert sorted(grouped["stable"]) == sorted(W46_EXPECTED_CHANGES["stable"])
    assert summarize_changes(changes) == {
        "new": 1,
        "gone": 1,
        "stronger": 1,
        "weaker": 1,
        "stable": 3,
    }


def test_w46_gone_rule_does_not_pass_filter() -> None:
    """消失组合 B05>B04 在 W46 不产生任何通过过滤的方向规则（因此进不了新陈列建议）。"""
    identities = {row["rule_key"].split("@")[-1] for row in _passed(build_w46_baskets(), "W46")}
    assert "B05>B04" not in identities
    assert "B04>B05" not in identities


def test_w46_change_directions_are_numeric_consistent() -> None:
    changes = diff_rules(_passed(build_baskets(), "W45"), _passed(build_w46_baskets(), "W46"))
    by_type = {row["change_type"]: row for row in changes}
    assert by_type["stronger"]["lift_delta"] > 0
    assert by_type["weaker"]["lift_delta"] < 0
    assert by_type["new"]["baseline"]["lift"] is None
    assert by_type["gone"]["current"]["lift"] is None
