"""共享枚举（后端定义，前端 frontend/src/constants/enums.ts 必须一致）。

README「枚举出现位置」列出全部落点：
  backend/src/constants/enums.py（定义）
  backend/src/constants/roles.py（角色）
  backend/src/models/*.py（列默认值/约束）
  backend/src/schemas/*.py（响应枚举）
  backend/src/services/*.py（状态流转）
  frontend/src/constants/enums.ts（镜像定义）
  frontend/src/constants/roles.ts（角色镜像）
  frontend/src/pages/*.vue + components/common/*.vue（展示映射）
"""
from __future__ import annotations

from enum import Enum


class StoreTier(str, Enum):
    """门店客流分层（算法 2 稳定性校验维度）。"""

    HIGH = "high"   # 高客流店
    MID = "mid"     # 中客流店
    LOW = "low"     # 低客流店


class RunStatus(str, Enum):
    """挖掘批次状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RuleStatus(str, Enum):
    """规则状态（候选 → 采纳/驳回/挂起）。"""

    CANDIDATE = "candidate"
    ADOPTED = "adopted"
    REJECTED = "rejected"
    PARKED = "parked"


class ReviewDecision(str, Enum):
    """复核动作。"""

    ADOPT = "adopt"
    REJECT = "reject"
    PARK = "park"


class SlotStatus(str, Enum):
    """陈列建议位状态。"""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Channel(str, Enum):
    """小票来源渠道。"""

    POS = "pos"
    SELF_CHECKOUT = "self_checkout"
    MINI_PROGRAM = "mini_program"


class RuleChangeType(str, Enum):
    """周度批次对比：同一规则组合（剥离批次前缀后的 rule identity）的变化类型。"""

    NEW = "new"             # 新批次出现、基线批次没有
    GONE = "gone"           # 基线批次有、新批次已消失（跌出支持度/过滤阈值）
    STRONGER = "stronger"   # 两批都在，lift 相对增幅超过阈值 → 增强
    WEAKER = "weaker"       # 两批都在，lift 相对降幅超过阈值 → 减弱
    STABLE = "stable"       # 两批都在，lift 变化在阈值内 → 持平


class BatchSource(str, Enum):
    """小票批次来源。"""

    SEED = "seed"       # 内置确定性 fixture
    IMPORT = "import"   # 运营补入的周度小票


TIER_LABELS: dict[str, str] = {
    StoreTier.HIGH.value: "高客流店",
    StoreTier.MID.value: "中客流店",
    StoreTier.LOW.value: "低客流店",
}

RUN_STATUS_LABELS: dict[str, str] = {
    RunStatus.QUEUED.value: "排队中",
    RunStatus.RUNNING.value: "挖掘中",
    RunStatus.SUCCEEDED.value: "已完成",
    RunStatus.FAILED.value: "失败",
}

RULE_STATUS_LABELS: dict[str, str] = {
    RuleStatus.CANDIDATE.value: "待复核",
    RuleStatus.ADOPTED.value: "已采纳",
    RuleStatus.REJECTED.value: "已驳回",
    RuleStatus.PARKED.value: "已挂起",
}

REVIEW_DECISION_LABELS: dict[str, str] = {
    ReviewDecision.ADOPT.value: "采纳",
    ReviewDecision.REJECT.value: "驳回",
    ReviewDecision.PARK.value: "挂起",
}

SLOT_STATUS_LABELS: dict[str, str] = {
    SlotStatus.DRAFT.value: "待发布",
    SlotStatus.PUBLISHED.value: "已发布",
    SlotStatus.ARCHIVED.value: "已归档",
}

CHANNEL_LABELS: dict[str, str] = {
    Channel.POS.value: "收银机 POS",
    Channel.SELF_CHECKOUT.value: "自助收银",
    Channel.MINI_PROGRAM.value: "小程序扫码",
}

RULE_CHANGE_LABELS: dict[str, str] = {
    RuleChangeType.NEW.value: "新增",
    RuleChangeType.GONE.value: "消失",
    RuleChangeType.STRONGER.value: "增强",
    RuleChangeType.WEAKER.value: "减弱",
    RuleChangeType.STABLE.value: "持平",
}

BATCH_SOURCE_LABELS: dict[str, str] = {
    BatchSource.SEED.value: "内置样本",
    BatchSource.IMPORT.value: "周度补入",
}
