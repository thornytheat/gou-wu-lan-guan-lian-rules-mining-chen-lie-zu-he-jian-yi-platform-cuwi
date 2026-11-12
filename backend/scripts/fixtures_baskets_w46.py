"""W46 周度小票生成器（确定性、独立于 W45 fixture，专用于批次对比演示）。

设计目标——同一套 Apriori/过滤口径下，相对 W45（RUN-2026-W41-DEMO）稳定产出五类变化：

  增强  N01>N02 啤酒→花生   共现 51 → 64（lift 明显上行）
  减弱  N07>N06 泡面→火腿   共现 41 → 35、lift 1.96 → 1.85（仍通过 lift>1.2/conf>0.25，属减弱而非消失）
  消失  B05>B04 咖啡→饭团   共现 35 →  0（该对不再共现，跌出频繁项集）
  新增  I08>C01 矿泉水→绿茶 共现  0 → 42（W45 里被 29 张封顶，W46 预埋为强对）
  持平  N04>N05 / B03>B02 / N08>N03 共现不变

实现方式：复用 fixtures_baskets 的生成/派元机制，只替换两份「计划」（PAIR_BUNDLES 与
FILLER_WEIGHTS）并换随机种子/时间窗/小票号前缀；不修改 W45 的任何常量，原有 46/12/6 口径不变。
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

from scripts import fixtures, fixtures_baskets

W46_RNG_SEED = 20261119
W46_SAMPLE_START = "2026-10-12"
W46_SAMPLE_DAYS = 7
W46_BASKET_TOTAL = fixtures.BASKET_TOTAL  # 3000 张，两批样本量一致，对比差异只来自结构
W46_BASKET_PREFIX = "W46"

# 共现计划：键 = W45 共现 → W46 共现
W46_PAIR_SPECS: list[dict] = [
    {"key": "N01>N02", "cooccur": 64},   # 增强（51 → 64）
    {"key": "N04>N05", "cooccur": 44},   # 持平
    # 减弱：共现 41 → 35、trigger 155 → 132（保置信度）、后项 N06 独立量 405 → 430（压 lift）
    {"key": "N07>N06", "cooccur": 35, "trigger_baskets": 132, "attach_baskets": 430},
    {"key": "B03>B02", "cooccur": 37},   # 持平
    # B05>B04 刻意移除 → 消失
    {"key": "N08>N03", "cooccur": 44},   # 持平
    {"key": "I08>C01", "cooccur": 42},   # 新增（W45 无预埋）
]


def _w46_pair_bundles() -> list[dict]:
    """沿用 W45 各 SKU 的 trigger/attach 总量，只替换共现数；新增对补一组合理总量。"""
    base = {spec["key"]: dict(spec) for spec in fixtures.PAIR_BUNDLES}
    bundles: list[dict] = []
    for spec in W46_PAIR_SPECS:
        if spec["key"] in base:
            merged = dict(base[spec["key"]])
            merged["cooccur"] = spec["cooccur"]
            # 允许 W46 显式收紧 trigger/attach 总量（减弱规则保置信度用）
            if "trigger_baskets" in spec:
                merged["trigger_baskets"] = spec["trigger_baskets"]
            if "attach_baskets" in spec:
                merged["attach_baskets"] = spec["attach_baskets"]
            bundles.append(merged)
        else:
            # 新增对 I08>C01：给 trigger/attach 总量，使 conf≈0.26、lift≈1.8 量级
            bundles.append(
                {
                    "key": spec["key"],
                    "left": "I08",
                    "right": "C01",
                    "cooccur": spec["cooccur"],
                    "trigger_baskets": 158,
                    "attach_baskets": 405,
                    "expected_lift": 1.8,
                    "zone": "H1 水饮层",
                    "zone_code": "H1",
                    "shelf_label": "H1 水饮层 · 端头上格",
                    "note": "W46 新增强关联：矿泉水与无糖绿茶相邻陈列。",
                }
            )
    return bundles


def _w46_filler_weights() -> dict[str, int]:
    """B05/B04 退出预埋对后回归普通长尾；I08/C01 进入预埋对，从长尾池移除。"""
    weights = dict(fixtures.FILLER_WEIGHTS)
    weights.pop("I08", None)  # I08 在 W46 是预埋对成员
    # C01 本就在 FILLER_WEIGHTS 中，移除避免与预埋身份冲突
    weights.pop("C01", None)
    # B05/B04 不在 FILLER_WEIGHTS（原本就是预埋成员），补回长尾权重
    weights.setdefault("B05", 180)
    weights.setdefault("B04", 176)
    return weights


def _w46_plan_module() -> SimpleNamespace:
    return SimpleNamespace(
        PAIR_BUNDLES=_w46_pair_bundles(),
        FILLER_WEIGHTS=_w46_filler_weights(),
        BASKET_TOTAL=W46_BASKET_TOTAL,
    )


def _build_w46_rows() -> list[dict]:
    """以 W46 计划跑一遍与 W45 同构的原始行生成（临时替换模块常量，不动源文件）。"""
    orig_bundles = fixtures_baskets.fixtures.PAIR_BUNDLES
    orig_weights = fixtures_baskets.fixtures.FILLER_WEIGHTS
    orig_seed = fixtures_baskets.RNG_SEED
    plan_module = _w46_plan_module()
    fixtures_baskets.fixtures.PAIR_BUNDLES = plan_module.PAIR_BUNDLES
    fixtures_baskets.fixtures.FILLER_WEIGHTS = plan_module.FILLER_WEIGHTS
    fixtures_baskets.RNG_SEED = W46_RNG_SEED
    try:
        rows, plan_data = fixtures_baskets._build_raw()
    finally:
        fixtures_baskets.fixtures.PAIR_BUNDLES = orig_bundles
        fixtures_baskets.fixtures.FILLER_WEIGHTS = orig_weights
        fixtures_baskets.RNG_SEED = orig_seed
    return rows


def build_w46_baskets() -> list[dict]:
    """生成 3,000 张 W46 小票（时间窗 2026-10-12 ~ 10-18，小票号 W46 前缀）。"""
    rows = _build_w46_rows()
    rng = random.Random(W46_RNG_SEED + 7)
    stores = fixtures.DEMO_STORES
    by_tier: dict[str, list[dict]] = defaultdict(list)
    for store in stores:
        by_tier[store["tier"]].append(store)

    pair_tiers = ["high", "mid", "low"] * 120
    pair_cursor = 0
    store_cursor = 0
    for row in rows:
        if row.get("tag", "").startswith("pair:"):
            tier = pair_tiers[pair_cursor % len(pair_tiers)]
            pair_cursor += 1
            row["store"] = by_tier[tier][pair_cursor % len(by_tier[tier])]
        else:
            row["store"] = stores[store_cursor % len(stores)]
            store_cursor += 1

    rng.shuffle(rows)
    prices = fixtures.sku_price_map()
    fresh_codes = {"I08", "N08", "I01"}
    start = date.fromisoformat(W46_SAMPLE_START)
    tz = fixtures_baskets.TZ
    hours = fixtures_baskets.HOURS
    baskets: list[dict] = []
    for index, row in enumerate(rows):
        day = index % W46_SAMPLE_DAYS
        hour = hours[(index * 3) % len(hours)]
        minute = (index * 11) % 60
        ts = datetime.combine(start + timedelta(days=day), time(hour=hour, minute=minute), tzinfo=tz)
        lines = []
        total = 0.0
        for code in row["items"]:
            qty = 2 if (code in fresh_codes and index % 9 == 0) else 1
            amount = round(prices[code] * qty, 2)
            total += amount
            lines.append({"sku": code, "qty": qty, "amount": f"{amount:.2f}"})
        baskets.append(
            {
                "basket_no": f"BR-{W46_BASKET_PREFIX}-{ts.strftime('%Y%m%d')}-{index + 1:05d}",
                "store_code": row["store"]["code"],
                "store_name": row["store"]["name"],
                "store_tier": row["store"]["tier"],
                "channel": fixtures.CHANNELS[index % len(fixtures.CHANNELS)],
                "basket_ts": ts,
                "net_amount": f"{round(total, 2):.2f}",
                "item_count": len(lines),
                "lines": lines,
            }
        )
    if len(baskets) != W46_BASKET_TOTAL:
        raise RuntimeError(f"W46 小票数不符：{len(baskets)} != {W46_BASKET_TOTAL}")
    return baskets


W46_EXPECTED_CHANGES = {
    "stronger": ["N01>N02"],
    "weaker": ["N07>N06"],
    "gone": ["B05>B04"],
    "new": ["I08>C01"],
    "stable": ["N04>N05", "B03>B02", "N08>N03"],
}
