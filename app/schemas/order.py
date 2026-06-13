"""订单 schema (Spec 4.5)。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class OrderItemIn(BaseModel):
    camera_config_id: str
    quantity: int = Field(default=1, ge=1)


class OrderCreateRequest(BaseModel):
    items: List[OrderItemIn]
    rental_start: date
    rental_end: date
    delivery_address_id: Optional[str] = None
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
    subtotal: Decimal
    deposit: Decimal
    discount_amount: Decimal
    total_price: Decimal
    paid_amount: Decimal
    rental_start: date
    rental_end: date
    version: int
    items: List[OrderItemOut] = []


class OrderCreateResponse(BaseModel):
    order_id: str
    status: str
    total_price: Decimal
    deposit: Decimal
    payment_instruction: str
    reservation_expires_at: Optional[str] = None


class OrderExtendRequest(BaseModel):
    action: str = "extend"
    new_end_date: date
    version: Optional[int] = None


class PaymentConfirmRequest(BaseModel):
    paid_amount: Decimal
    payment_note: Optional[str] = None
    version: Optional[int] = None


class StatusAdvanceRequest(BaseModel):
    target: str
    version: Optional[int] = None


class CancelResponse(BaseModel):
    order_id: str
    status: str
    refund_amount: Decimal
    cancellation_fee: Decimal
