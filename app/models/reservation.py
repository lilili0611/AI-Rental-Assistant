"""库存预留模型。

🔴 修正(Spec 2.7): 预留必须带 rental_start/rental_end,
否则无法在 occupancy 表中正确登记日期区间。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Reservation(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "reservations"

    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), index=True
    )
    camera_config_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("camera_configs.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    rental_start: Mapped[date] = mapped_column(Date, nullable=False)
    rental_end: Mapped[date] = mapped_column(Date, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # active / confirmed / expired / cancelled
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    order_id: Mapped[Optional[str]] = mapped_column(
        String(30), ForeignKey("orders.id")
    )
