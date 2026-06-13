"""设备与设备配置模型。

🔴 修正(Spec 2.2/2.3): 设备与配置表不再保存任何库存计数字段。
库存改由 occupancy 占用表按日期动态计算; 配置表仅保留实物总台数 total_units。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import ForeignKey, Integer, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Camera(Base, TimestampMixin):
    __tablename__ = "cameras"

    # 设备 ID 是业务可读字符串，如 "R5"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    brand: Mapped[Optional[str]] = mapped_column(String(50))
    model: Mapped[Optional[str]] = mapped_column(String(100))
    # 列表展示用的"起租价"(两天租金起, 实际计费以配置表为准)
    daily_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    deposit_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    specs: Mapped[dict] = mapped_column(JSON, default=dict)
    # Phase 3 RAG 关联
    knowledge_entry_id: Mapped[Optional[str]] = mapped_column(String(100))

    configs: Mapped[list["CameraConfig"]] = relationship(
        back_populates="camera", cascade="all, delete-orphan"
    )


class CameraConfig(Base, TimestampMixin):
    __tablename__ = "camera_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    camera_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("cameras.id"), index=True, nullable=False
    )
    config_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 🔴 实物总台数(静态)。某日可用数 = total_units - 该日占用数
    total_units: Mapped[int] = mapped_column(Integer, nullable=False)
    # 档位计价(取代日租×折扣模型):
    #   1-2天 -> two_day_price; 3天 -> three_day_price;
    #   >3天 -> three_day_price + (天数-3) × extra_day_price
    two_day_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    three_day_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    extra_day_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    deposit_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    accessories: Mapped[list] = mapped_column(JSON, default=list)

    camera: Mapped["Camera"] = relationship(back_populates="configs")
    units: Mapped[list["InventoryUnit"]] = relationship(
        back_populates="config", cascade="all, delete-orphan"
    )
