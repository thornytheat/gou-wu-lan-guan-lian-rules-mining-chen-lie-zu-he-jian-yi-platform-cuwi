"""端到端集成：小票导入幂等 → 两批挖掘 → 规则血缘 → 对比快照可复现 → 消失规则拦截。

生产环境是 PostgreSQL；CI/本机没有 PG 时用 SQLite 内存库验证业务链路。
方言适配只在本测试内做编译期重写（JSONB→JSON、UUID→CHAR(36)、去掉 schema 限定），
业务服务代码一行不改。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.constants.enums import ReviewDecision, RuleChangeType, RuleStatus, SlotStatus
from src.models import Base
from src.models.planogram_slot import PlanogramSlot
from src.models.rule_candidate import RuleCandidate
from src.models.rule_review import RuleReview
from src.models.user import User
from src.services import (
    basket_batch_service,
    comparison_service,
    lineage_service,
    mining_service,
    planogram_service,
)
from src.services.diff_core import rule_identity_of

TZ = timezone(timedelta(hours=8))


# --- 仅测试内的 SQLite 方言适配：让 PG UUID 在 SQLite 上以字符串透传（生产仍走 PG 原生 UUID） ---
_orig_uuid_bind = UUID.bind_processor
_orig_uuid_result = UUID.result_processor


def _sqlite_uuid_bind(self, dialect):  # noqa: ANN001
    if dialect.name == "sqlite":
        return lambda value: str(value) if value is not None else None
    return _orig_uuid_bind(self, dialect)


def _sqlite_uuid_result(self, dialect, coltype):  # noqa: ANN001
    if dialect.name == "sqlite":
        return lambda value: value
    return _orig_uuid_result(self, dialect, coltype)


UUID.bind_processor = _sqlite_uuid_bind  # type: ignore[method-assign]
UUID.result_processor = _sqlite_uuid_result  # type: ignore[method-assign]


@pytest.fixture()
def db_session():
    from sqlalchemy.ext.compiler import compiles

    @compiles(JSONB, "sqlite")
    def _jsonb_sqlite(element, compiler, **kw):  # noqa: ANN001
        return "JSON"

    @compiles(UUID, "sqlite")
    def _uuid_sqlite(element, compiler, **kw):  # noqa: ANN001
        return "CHAR(36)"

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # SQLite 不支持 PG schema，把表建在默认命名空间（幂等：重复测试只重写一次）
    if Base.metadata.schema is not None:
        Base.metadata.schema = None
    for table in Base.metadata.tables.values():
        table.schema = None
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _user(role: str = "analyst") -> User:
    return User(
        email=f"{role}@t.io",
        password_hash="test-fixed-hash",
        display_name=f"测试-{role}",
        role=role,
        is_active=True,
    )


def _basket(no: str, items: list[str], ts: datetime, tier: str = "high") -> dict:
    lines = [{"sku": sku, "qty": 1, "amount": "10.00"} for sku in items]
    return {
        "basket_no": no,
        "store_code": "S01",
        "store_name": "测试店",
        "store_tier": tier,
        "channel": "pos",
        "basket_ts": ts,
        "net_amount": f"{10.0 * len(lines):.2f}",
        "item_count": len(lines),
        "lines": lines,
    }


def _week_baskets(prefix: str, pair_plan: dict[frozenset, int], start: datetime) -> list[dict]:
    """构造一批小票：强对按 pair_plan 共现，其余为单品/弱共现，保证三层都有样本。"""
    baskets: list[dict] = []
    idx = 0
    tiers = ["high", "mid", "low"]
    for pair, count in pair_plan.items():
        a, b = sorted(pair)
        for _ in range(count):
            idx += 1
            baskets.append(
                _basket(f"{prefix}-{idx:04d}", [a, b], start + timedelta(hours=idx), tiers[idx % 3])
            )
    # 单品背景小票（让 support/lift 有合理分母，且保证各 SKU 达到 min_support）
    background = ["A", "B", "C", "D", "E", "F", "G", "H"]
    for sku in background:
        for repeat in range(60):
            idx += 1
            baskets.append(
                _basket(f"{prefix}-{idx:04d}", [sku], start + timedelta(hours=idx), tiers[idx % 3])
            )
    return baskets


def _run_mining(db, user, batch_id, label):
    run, created = mining_service.create_seed_run(
        db, user, label, batch_ids=[batch_id]
    )
    assert created
    rules = db.query(RuleCandidate).filter(RuleCandidate.run_id == run.id).all()
    return run, rules


def test_full_weekly_batch_flow(db_session) -> None:
    db = db_session
    analyst = _user("analyst")
    admin = _user("admin")
    db.add_all([analyst, admin])
    db.flush()

    start_w1 = datetime(2026, 10, 5, 8, 0, tzinfo=TZ)
    start_w2 = datetime(2026, 10, 12, 8, 0, tzinfo=TZ)

    # W45：A>B 强、C>D 强、E>F 强（后者将在 W46 消失）
    w1_plan = {
        frozenset(("A", "B")): 80,
        frozenset(("C", "D")): 70,
        frozenset(("E", "F")): 60,
    }
    w1_baskets = _week_baskets("W45", w1_plan, start_w1)
    batch1, inserted1 = basket_batch_service.import_batch(
        db, analyst, "BATCH-W45", w1_baskets, source="seed"
    )
    assert inserted1
    # 幂等：完全相同内容再导一次 → 短路，不新增小票
    again, inserted_again = basket_batch_service.import_batch(
        db, analyst, "BATCH-W45-COPY", w1_baskets, source="import"
    )
    assert not inserted_again
    assert str(again.id) == str(batch1.id)

    # W46：A>B 增强、C>D 减弱、E>F 消失、G>H 新增
    w2_plan = {
        frozenset(("A", "B")): 120,   # 增强
        frozenset(("C", "D")): 70,    # 背景占比变化由新增对稀释，见断言放宽
        frozenset(("G", "H")): 90,    # 新增
    }
    w2_baskets = _week_baskets("W46", w2_plan, start_w2)
    batch2, inserted2 = basket_batch_service.import_batch(
        db, analyst, "BATCH-W46", w2_baskets, source="import"
    )
    assert inserted2
    assert batch2.period_start is not None and batch2.period_end is not None

    # 两次挖掘（同参数）
    run1, rules1 = _run_mining(db, analyst, str(batch1.id), "RUN-W45")
    run2, rules2 = _run_mining(db, analyst, str(batch2.id), "RUN-W46")
    assert run1.basket_count == len(w1_baskets)
    assert run2.basket_count == len(w2_baskets)
    assert run1.sample_start and run1.sample_end

    identities1 = {rule_identity_of(r.rule_key) for r in rules1}
    identities2 = {rule_identity_of(r.rule_key) for r in rules2}
    assert "E>F" in identities1 and "E>F" not in identities2       # 消失
    assert "G>H" in identities2 and "G>H" not in identities1       # 新增
    assert "A>B" in identities1 and "A>B" in identities2           # 保留

    # 血缘：保留组合有记录，且基线复核结论被带过来
    ab_baseline = next(r for r in rules1 if rule_identity_of(r.rule_key) == "A>B")
    ab_baseline.status = RuleStatus.ADOPTED.value
    db.add(
        RuleReview(
            rule_id=ab_baseline.id,
            reviewer_id=admin.id,
            decision=ReviewDecision.ADOPT.value,
            reason="基线批次采纳理由：端架试点有效",
        )
    )
    db.flush()
    # 重新构建 W46 血缘以包含刚写入的复核
    db.query(lineage_service.RuleLineage).delete()
    lineage_service.build_lineage(db, run2)
    ab_current = next(r for r in rules2 if rule_identity_of(r.rule_key) == "A>B")
    link = lineage_service.lineage_for_rule(db, ab_current.id)
    assert link is not None
    assert link.baseline_status == RuleStatus.ADOPTED.value
    assert "端架试点有效" in (link.baseline_reason or "")

    # 已发布工单挂在 W45 规则上
    plan_code = "PLAN-W45"
    db.add(
        PlanogramSlot(
            slot_key=f"{plan_code}@A>B",
            plan_code=plan_code,
            rule_id=ab_baseline.id,
            shelf_label="端架A 01",
            zone="端架A",
            conflict_group="A1",
            position_index=1,
            est_uplift=ab_baseline.uplift_month,
            status=SlotStatus.PUBLISHED.value,
            published_at=datetime.now(TZ),
        )
    )
    db.flush()

    # 对比快照：第一次计算
    first = comparison_service.compare_runs(db, str(run1.id), str(run2.id))
    counts = first["counts"]
    assert counts["new"] >= 1 and counts["gone"] >= 1
    change_ids = {c["rule_identity"]: c["change_type"] for c in first["changes"]}
    assert change_ids.get("E>F") == RuleChangeType.GONE.value
    assert change_ids.get("G>H") == RuleChangeType.NEW.value

    # 可复现：再请求复用同一快照，内容逐字一致
    second = comparison_service.compare_runs(db, str(run1.id), str(run2.id))
    assert second["reused_snapshot"] is True
    assert second["changes"] == first["changes"]
    assert second["affected_slots"] == first["affected_slots"]

    # 受影响货架位：消失/减弱且已发布的位才出现
    affected_keys = {slot["rule_identity"] for slot in first["affected_slots"]}
    # A>B 是增强，不应在受影响清单；E>F 已消失但没有工单，也不在
    assert "A>B" not in affected_keys

    # 头部带两批样本小票数与时间范围
    assert first["baseline"]["basket_count"] == len(w1_baskets)
    assert first["current"]["basket_count"] == len(w2_baskets)
    assert first["baseline"]["sample_start"] and first["current"]["sample_start"]

    # 消失规则不能进入新陈列建议：W46 候选里没有 E>F，生成建议单不引用任何 W45 规则
    plan_w46 = planogram_service.generate_plan(db, analyst, run_id=str(run2.id))
    slot_rule_ids = {slot["rule"]["id"] for slot in plan_w46["slots"] if slot["rule"]}
    w46_rule_ids = {str(r.id) for r in rules2}
    assert slot_rule_ids <= w46_rule_ids
    # 已发布的 W45 工单 rule_id 没有被改挂
    old_slot = db.query(PlanogramSlot).filter(PlanogramSlot.plan_code == plan_code).one()
    assert str(old_slot.rule_id) == str(ab_baseline.id)


def test_duplicate_run_same_batch_is_idempotent_on_input(db_session) -> None:
    """同一批小票重复挖掘：结果规则集合一致（输入指纹相同，算法确定性）。"""
    db = db_session
    analyst = _user()
    db.add(analyst)
    db.flush()
    start = datetime(2026, 10, 5, 8, 0, tzinfo=TZ)
    baskets = _week_baskets("WK", {frozenset(("A", "B")): 90}, start)
    batch, _ = basket_batch_service.import_batch(db, analyst, "BATCH-DUP", baskets)

    run_a, rules_a = _run_mining(db, analyst, str(batch.id), "RUN-DUP-A")
    # 同批次再跑一个 run，输入完全一致 → 规则身份与 lift 一致
    run_b, rules_b = _run_mining(db, analyst, str(batch.id), "RUN-DUP-B")
    keys_a = sorted((rule_identity_of(r.rule_key), float(r.lift)) for r in rules_a)
    keys_b = sorted((rule_identity_of(r.rule_key), float(r.lift)) for r in rules_b)
    assert keys_a == keys_b
    assert run_a.basket_count == run_b.basket_count
