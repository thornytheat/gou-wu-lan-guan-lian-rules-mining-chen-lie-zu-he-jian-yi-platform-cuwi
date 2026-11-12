"""把 scripts/fixtures.py 的规则元数据（分区 / 货架位 / 备注）暴露给服务层。"""
from __future__ import annotations

from scripts import fixtures


def rule_meta(rule_key: str) -> dict:
    """rule_key 形如 'N01>N02' 或带 run 前缀，取最后一段匹配 fixture。"""
    tail = rule_key.split("@")[-1]
    for spec in fixtures.PAIR_BUNDLES:
        if spec["key"] == tail:
            return spec
    # 周度新规则的货架扩展（不参与 W45 小票生成）
    if tail in fixtures.EXTRA_RULE_ZONES:
        return fixtures.EXTRA_RULE_ZONES[tail]
    left, _, right = tail.partition(">")
    for spec in fixtures.PAIR_BUNDLES:
        if {spec["left"], spec["right"]} == {left, right}:
            return spec
    for spec in fixtures.EXTRA_RULE_ZONES.values():
        spec_left, _, spec_right = spec["key"].partition(">")
        if {spec_left, spec_right} == {left, right}:
            return spec
    return {}


def zone_payload(rule_key: str) -> dict:
    meta = rule_meta(rule_key)
    return {
        "zone": meta.get("zone", "未分配货架区"),
        "zone_code": meta.get("zone_code", ""),
        "shelf_label": meta.get("shelf_label", "待定货架位"),
        "note": meta.get("note", ""),
    }
