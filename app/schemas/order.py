"""订单 schema (Spec 4.5)。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class OrderItemIn(BaseModel):
    camera_config_id: str
    quantity: int = Field(default=1, ge=1)


class ShippingAddressIn(BaseModel):
    receiver_name: str = Field(min_length=2, max_length=100)
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")
    province: str = Field(min_length=2, max_length=50)
    city: str = Field(min_length=2, max_length=50)
    district: str = Field(min_length=2, max_length=50)
    detail_address: str = Field(min_length=5, max_length=200)

    @field_validator(
        "receiver_name", "phone", "province", "city", "district", "detail_address",
        mode="before",
    )
    @classmethod
    def strip_required_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class ShippingAddressOut(BaseModel):
    receiver_name: str
    phone: str
    province: str
    city: str
    district: str
    detail_address: str
    full_address: str


class OrderCreateRequest(BaseModel):
    items: List[OrderItemIn] = Field(min_length=1)
    rental_start: date
    rental_end: date
    shipping_address: ShippingAddressIn
    reservation_id: Optional[str] = None


class OrderItemOut(BaseModel):
    camera_config_id: str
    quantity: int
    price_per_day: Decimal
    discount_rate: Decimal
    subtotal: Decimal


class OrderOut(BaseModel):
    order_id: str
    status: str
    display_status: str  # 🆕 v2.1 客户/商家可见中文标签
    subtotal: Decimal
    deposit: Decimal
    discount_amount: Decimal
    total_price: Decimal
    paid_amount: Decimal
    rental_start: date
    rental_end: date
    version: int
    carrier: Optional[str] = None  # 🆕 v2.1 快递公司
    tracking_no: Optional[str] = None  # 🆕 v2.1 物流单号
    review_note: Optional[str] = None  # 🆕 v2.1 审核驳回原因
    shipping_address: Optional[ShippingAddressOut] = None
    user_id: Optional[str] = None  # 商家端列表用
    items: List[OrderItemOut] = []


class OrderCreateResponse(BaseModel):
    order_id: str
    status: str
    total_price: Decimal
    deposit: Decimal
    shipping_address: ShippingAddressOut
    payment_instruction: str
    reservation_expires_at: Optional[str] = None


class OrderExtendRequest(BaseModel):
    action: str = "extend"
    new_end_date: date
    version: Optional[int] = None


class PaymentConfirmRequest(BaseModel):
    paid_amount: Decimal = Field(ge=0)
    payment_note: Optional[str] = None
    version: Optional[int] = None


class StatusAdvanceRequest(BaseModel):
    target: str
    version: Optional[int] = None


# 🆕 v2.1 商家审核
class ReviewRequest(BaseModel):
    approve: bool
    paid_amount: Optional[Decimal] = Field(default=None, ge=0)
    rent_amount: Optional[Decimal] = Field(default=None, ge=0)
    payment_note: Optional[str] = None
    review_note: Optional[str] = None
    version: Optional[int] = None


class RentUpdateRequest(BaseModel):
    rent_amount: Decimal = Field(ge=0)
    reason: Optional[str] = None
    version: Optional[int] = None


# 🆕 v2.1 上传物流并发货
class ShipRequest(BaseModel):
    carrier: str
    tracking_no: str
    version: Optional[int] = None


# 🆕 v2.1 商家验收完结
class AcceptRequest(BaseModel):
    version: Optional[int] = None


class CancelResponse(BaseModel):
    order_id: str
    status: str
    refund_amount: Decimal
    cancellation_fee: Decimal
