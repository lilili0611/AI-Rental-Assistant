"""预留服务 (Spec 2.7 / 3.2)。

下单前先预留库存 30 分钟; 到期未转单则自动释放。
预留必须带日期区间, 并在 occupancy 表登记对应区间的占用。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.camera import CameraConfig
from app.models.inventory import Occupancy
from app.models.reservation import Reservation
from app.services import inventory_service


class InventoryError(Exception):
    """库存不足等库存相关错误。"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


def create_reservation(
    db: Session,
    config: CameraConfig,
    quantity: int,
    start: date,
    end: date,
    user_id: Optional[str] = None,
) -> Reservation:
    """创建预留并登记占用。库存不足抛 InventoryError。"""
    avail = inventory_service.get_config_availability(db, config, start, end)
    if avail.min_available_in_range < quantity:
        shortage_days = [
            {"date": d.day.isoformat(), "available": d.available}
            for d in avail.daily_breakdown
            if d.available < quantity
        ]
        raise InventoryError(
            f"库存不足: {config.config_name} 在所选区间最多可租 "
            f"{avail.min_available_in_range} 台(需 {quantity} 台)",
            details={
                "config_id": config.id,
                "requested": quantity,
                "min_available": avail.min_available_in_range,
                "shortage_days": shortage_days,
            },
        )

    expires_at = datetime.now() + timedelta(minutes=settings.reservation_ttl_minutes)
    reservation = Reservation(
        user_id=user_id,
        camera_config_id=config.id,
        quantity=quantity,
        rental_start=start,
        rental_end=end,
        expires_at=expires_at,
        status="active",
    )
    db.add(reservation)
    db.flush()  # 拿到 reservation.id

    # 方案 A: 每台一条占用记录
    for _ in range(quantity):
        db.add(
            Occupancy(
                config_id=config.id,
                occupancy_type="reservation",
                start_date=start,
                end_date=end,
                ref_id=reservation.id,
                expires_at=expires_at,
                status="active",
            )
        )
    db.flush()
    return reservation


def release_reservation(db: Session, reservation: Reservation, new_status: str) -> None:
    """释放预留对应的占用记录(取消/过期)。"""
    reservation.status = new_status
    occs = db.execute(
        select(Occupancy).where(
            Occupancy.ref_id == reservation.id,
            Occupancy.occupancy_type == "reservation",
            Occupancy.status == "active",
        )
    ).scalars().all()
    for occ in occs:
        occ.status = "released" if new_status == "cancelled" else "expired"
    db.flush()


def sweep_expired(db: Session) -> int:
    """扫描并释放已过期的预留。返回释放数量。供定时任务调用。"""
    now = datetime.now()
    expired = db.execute(
        select(Reservation).where(
            Reservation.status == "active",
            Reservation.expires_at < now,
        )
    ).scalars().all()
    for r in expired:
        release_reservation(db, r, "expired")
    if expired:
        db.commit()
    return len(expired)
