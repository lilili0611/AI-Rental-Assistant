"""订单、订单明细、订单变更审计模型。

🔴 修正(Spec 2.5): 移除任何支付二维码/支付通道字段。
支付由人工确认: paid_amount + payment_note 由财务/销售手动录入。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    # 业务可读订单号, 如 ORD20240601001
    id: Mapped[str] = mapped_column(String(30), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True, nullable=False
    )
    # 状态机见 services/order_service 与 Spec 3.1
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    deposit_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)

    # 🔴 人工录入的收款信息
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    payment_note: Mapped[Optional[str]] = mapped_column(String(500))

    # 🆕 v2.1 商家审核备注/驳回原因
    review_note: Mapped[Optional[str]] = mapped_column(String(500))
    # 🆕 v2.1 物流(商家手填, 前端只读展示, 不对接快递 API)
    carrier: Mapped[Optional[str]] = mapped_column(String(50))
    tracking_no: Mapped[Optional[str]] = mapped_column(String(100))

    rental_start: Mapped[date] = mapped_column(Date, nullable=False)
    rental_end: Mapped[date] = mapped_column(Date, nullable=False)

    delivery_address_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("user_addresses.id")
    )

    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    last_modified_by: Mapped[Optional[str]] = mapped_column(String(36))
    # 乐观锁版本号
    version: Mapped[int] = mapped_column(Integer, default=1)
    # ai / feishu / manual
    source: Mapped[str] = mapped_column(String(20), default="ai")
    # 飞书同步状态: synced / sync_pending / none
    sync_status: Mapped[str] = mapped_column(String(20), default="none")
    last_modified_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "order_items"

    order_id: Mapped[str] = mapped_column(
        String(30), ForeignKey("orders.id"), index=True, nullable=False
    )
    camera_config_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("camera_configs.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    # 下单时锁定的日价与综合折扣率
    price_per_day: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    discount_rate: Mapped[Decimal] = mapped_column(Numeric(5, 3), default=1)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)

    order: Mapped["Order"] = relationship(back_populates="items")


class OrderChange(Base, UUIDPKMixin):
    __tablename__ = "order_changes"

    order_id: Mapped[str] = mapped_column(
        String(30), ForeignKey("orders.id"), index=True, nullable=False
    )
    # create / update / cancel / return / status / payment
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_by: Mapped[Optional[str]] = mapped_column(String(36))
    changed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )
    old_value: Mapped[Optional[dict]] = mapped_column(JSON)
    new_value: Mapped[Optional[dict]] = mapped_column(JSON)
    reason: Mapped[Optional[str]] = mapped_column(String(500))
