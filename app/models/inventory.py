"""库存单元与占用记录模型 (方案 A: 精确到每台)。

🔴 这是修正库存逻辑的核心结构(Spec 2.4)。
- inventory_units: 每台实物一条记录。
- occupancy: 占用记录, 带 [start_date, end_date] 区间。
  "某配置在区间内是否有 N 台可用" = 对区间内每一天统计 active 占用数,
  确认 total_units - 占用数 >= N。算法见 services/inventory_service.py。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class InventoryUnit(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "inventory_units"

    config_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("camera_configs.id"), index=True, nullable=False
    )
    unit_label: Mapped[Optional[str]] = mapped_column(String(50))  # 实物编号/序列号
    # available / maintenance / retired
    status: Mapped[str] = mapped_column(String(20), default="available")

    config: Mapped["CameraConfig"] = relationship(back_populates="units")


class Occupancy(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "occupancy"

    config_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("camera_configs.id"), index=True, nullable=False
    )
    # 可后绑定具体台(预留阶段可为空)
    unit_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("inventory_units.id")
    )
    # reservation / order
    occupancy_type: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # 关联的预留 ID 或订单 ID
    ref_id: Mapped[Optional[str]] = mapped_column(String(36))
    # 预留占用的过期时间(订单占用为空)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # active / released / expired
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
