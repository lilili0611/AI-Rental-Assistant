"""业务规则常量与查表函数 —— 对应 PRD 第 3 章(已确认规则)。

集中管理可配置的业务参数, 便于业务方校准。
"""
from __future__ import annotations

from decimal import Decimal


# ============ 定价 ============
# 定价改为「档位计价」(两天/三天/续租)，见 services/pricing_service.py。
# 原 PRD 的天数阶梯折扣 + 季节折扣已按业务方价格表取代，不再使用。


# ============ 3.4 损坏赔偿规则 ============
# 每条: (上界 mm, 押金扣除比例)。区间按【左开右闭】无重叠处理:
# 取第一条满足 size <= 上界 的规则。上界 None 表示无上限(兜底)。
# 来源: PRD 3.4 整理后的精确区间。

# 机身/镜身划痕掉漆
SCRATCH_RULES = [
    (Decimal("2"), Decimal("0.02")),
    (Decimal("10"), Decimal("0.03")),
    (Decimal("30"), Decimal("0.10")),
    (None, Decimal("0.15")),  # > 30mm
]

# 机身/镜身磕碰磨损
DENT_RULES = [
    (Decimal("1"), Decimal("0.03")),
    (Decimal("3"), Decimal("0.05")),
    (Decimal("5"), Decimal("0.10")),
    (Decimal("10"), Decimal("0.15")),  # 5-10mm / 外壳裂痕<=5mm
    (Decimal("20"), Decimal("0.20")),  # 10-20mm / 外壳裂痕<=10mm
    (None, Decimal("1.00")),  # >=20mm 凹痕 / >=10mm 裂痕
]

# 镜片磨损
LENS_RULES = [
    (Decimal("1"), Decimal("0.05")),
    (Decimal("5"), Decimal("0.10")),
    (Decimal("10"), Decimal("0.20")),
    (None, Decimal("1.00")),  # >10mm 或镜片凹坑
]

DAMAGE_RULES = {
    "scratch": SCRATCH_RULES,   # 划痕掉漆
    "dent": DENT_RULES,         # 磕碰磨损
    "lens": LENS_RULES,         # 镜片磨损
}


def get_damage_rate(damage_type: str, size_mm: Decimal) -> Decimal:
    """根据损坏类型与实测尺寸(mm)返回押金扣除比例。"""
    rules = DAMAGE_RULES.get(damage_type)
    if rules is None:
        raise ValueError(f"未知损坏类型: {damage_type}")
    for upper, rate in rules:
        if upper is None or size_mm <= upper:
            return rate
    return Decimal("1.00")
