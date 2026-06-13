"""库存服务 —— 按日期的可用性计算 (Spec 5.1)。

🔴 核心修正点。库存不是全局计数, 而是按日期区间逐日计算:
  某配置在 [start, end] 区间是否有 N 台可用
  = 对区间内【每一天】, 统计该天 active 的 occupancy 数,
    确认 total_units − 占用数 >= N。
区间内每日可用数的【最小值】才是"整个租期能租几台"的正确答案。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.camera import CameraConfig
from app.models.inventory import Occupancy


def daterange(start: date, end: date):
    """生成 [start, end] 含端点的每一天。"""
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


@dataclass
class DayAvailability:
    day: date
    available: int


@dataclass
class ConfigAvailability:
    config_id: str
    config_name: str
    total_units: int
    min_available_in_range: int
    daily_breakdown: List[DayAvailability] = field(default_factory=list)

    @property
    def is_available(self) -> bool:
        return self.min_available_in_range > 0


def _active_occupancies(
    db: Session, config_id: str, start: date, end: date, exclude_ref_id: Optional[str]
) -> List[Occupancy]:
    """取出与 [start, end] 区间有交叠、且当前有效的占用记录。

    有效 = status='active' 且 (无过期时间 或 过期时间 > 现在)。
    区间交叠条件: occ.start_date <= end AND occ.end_date >= start。
    """
    now = datetime.now()
    stmt = select(Occupancy).where(
        Occupancy.config_id == config_id,
        Occupancy.status == "active",
        Occupancy.start_date <= end,
        Occupancy.end_date >= start,
        or_(Occupancy.expires_at.is_(None), Occupancy.expires_at > now),
    )
    if exclude_ref_id:
        stmt = stmt.where(
            or_(Occupancy.ref_id.is_(None), Occupancy.ref_id != exclude_ref_id)
        )
    return list(db.execute(stmt).scalars().all())


def get_config_availability(
    db: Session,
    config: CameraConfig,
    start: date,
    end: date,
    exclude_ref_id: Optional[str] = None,
) -> ConfigAvailability:
    """计算单个配置在区间内的逐日可用量与区间最小可用量。

    exclude_ref_id: 计算时排除某订单/预留自身的占用(改单场景用)。
    """
    occupancies = _active_occupancies(db, config.id, start, end, exclude_ref_id)
    total = config.total_units

    breakdown: List[DayAvailability] = []
    min_available = total
    for day in daterange(start, end):
        occupied = sum(
            occ_qty(occ)
            for occ in occupancies
            if occ.start_date <= day <= occ.end_date
        )
        available = total - occupied
        if available < 0:
            available = 0
        breakdown.append(DayAvailability(day=day, available=available))
        min_available = min(min_available, available)

    return ConfigAvailability(
        config_id=config.id,
        config_name=config.config_name,
        total_units=total,
        min_available_in_range=min_available,
        daily_breakdown=breakdown,
    )


def occ_qty(occ: Occupancy) -> int:
    """单条占用记录代表的台数。

    方案 A 中每条占用对应 1 台(占多台则拆成多条), 这里统一返回 1。
    若未来切换方案 B(占用表记数量), 在此返回 occ.quantity 即可。
    """
    return 1


def is_available(
    db: Session,
    config: CameraConfig,
    start: date,
    end: date,
    quantity: int,
    exclude_ref_id: Optional[str] = None,
) -> bool:
    """判断该配置在区间内是否有 quantity 台可用。"""
    avail = get_config_availability(db, config, start, end, exclude_ref_id)
    return avail.min_available_in_range >= quantity


def query_availability(
    db: Session,
    start: date,
    end: date,
    config_id: Optional[str] = None,
) -> List[ConfigAvailability]:
    """查询一个或全部配置在区间内的可用性。"""
    stmt = select(CameraConfig)
    if config_id:
        stmt = stmt.where(CameraConfig.id == config_id)
    configs = list(db.execute(stmt).scalars().all())
    return [get_config_availability(db, c, start, end) for c in configs]
