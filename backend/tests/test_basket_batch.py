"""小票批次内容指纹：规范化后同内容同指纹、导入顺序/字段顺序无关、不同内容不同指纹。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.services.basket_batch_service import _fingerprint, validate_baskets
from src.utils.errors import AppError

TZ = timezone(timedelta(hours=8))


def _basket(no: str, items: list[tuple[str, int]], ts: datetime) -> dict:
    lines = [{"sku": sku, "qty": qty, "amount": f"{qty * 5.5:.2f}"} for sku, qty in items]
    total = sum(line["qty"] * 5.5 for line in lines)
    return {
        "basket_no": no,
        "store_code": "S01",
        "store_name": "测试店",
        "store_tier": "high",
        "channel": "pos",
        "basket_ts": ts,
        "net_amount": f"{total:.2f}",
        "item_count": len(lines),
        "lines": lines,
    }


def _sample() -> list[dict]:
    base = datetime(2026, 10, 12, 9, 0, tzinfo=TZ)
    return [
        _basket("W46-001", [("N01", 1), ("N02", 2)], base),
        _basket("W46-002", [("N08", 1)], base + timedelta(hours=2)),
        _basket("W46-003", [("B03", 1), ("B02", 1), ("I08", 1)], base + timedelta(hours=5)),
    ]


def test_fingerprint_stable_for_identical_content() -> None:
    assert _fingerprint(_sample()) == _fingerprint(_sample())


def test_fingerprint_ignores_import_order() -> None:
    baskets = _sample()
    reversed_order = list(reversed(baskets))
    assert _fingerprint(baskets) == _fingerprint(reversed_order)


def test_fingerprint_ignores_line_order_but_catches_content_change() -> None:
    baskets = _sample()
    reordered_lines = [
        _basket(
            row["basket_no"],
            sorted([(line["sku"], line["qty"]) for line in row["lines"]], reverse=True),
            row["basket_ts"],
        )
        for row in baskets
    ]
    # 仅明细行顺序不同 → 同指纹（行内按 sku 排序规范化）
    assert _fingerprint(baskets) == _fingerprint(reordered_lines)

    changed = _sample()
    changed[0]["lines"][1]["qty"] = 9
    changed[0]["item_count"] = len(changed[0]["lines"])
    assert _fingerprint(baskets) != _fingerprint(changed)


def test_fingerprint_distinguishes_basket_no_and_timestamp() -> None:
    baskets = _sample()
    renamed = _sample()
    renamed[0]["basket_no"] = "W46-999"
    assert _fingerprint(baskets) != _fingerprint(renamed)

    shifted = _sample()
    shifted[1]["basket_ts"] = shifted[1]["basket_ts"] + timedelta(days=1)
    assert _fingerprint(baskets) != _fingerprint(shifted)


def test_validate_baskets_rejects_empty_and_missing_fields() -> None:
    with pytest.raises(AppError):
        validate_baskets([])
    bad = _sample()
    del bad[0]["store_code"]
    with pytest.raises(AppError):
        validate_baskets(bad)


def test_validate_baskets_rejects_duplicate_basket_no_and_empty_lines() -> None:
    dup = _sample()
    dup[1]["basket_no"] = dup[0]["basket_no"]
    with pytest.raises(AppError):
        validate_baskets(dup)

    no_lines = _sample()
    no_lines[0]["lines"] = []
    with pytest.raises(AppError):
        validate_baskets(no_lines)


def test_validate_baskets_rejects_naive_timestamp() -> None:
    baskets = _sample()
    baskets[0]["basket_ts"] = datetime(2026, 10, 12, 9, 0)  # 无时区
    with pytest.raises(AppError):
        validate_baskets(baskets)
