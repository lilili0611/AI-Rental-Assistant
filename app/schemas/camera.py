"""设备相关 schema (Spec 4.1)。"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel

from app.schemas.common import Pagination


class CameraBrief(BaseModel):
    id: str
    name: str
    brand: Optional[str] = None
    daily_price: Optional[Decimal] = None
    deposit_amount: Optional[Decimal] = None


class CameraListResponse(BaseModel):
    data: List[CameraBrief]
    pagination: Pagination


class ConfigOut(BaseModel):
    id: str
    config_name: str
    two_day_price: Decimal
    three_day_price: Decimal
    extra_day_price: Decimal
    deposit_amount: Decimal
    total_units: int
    accessories: List[str] = []


class CameraDetail(BaseModel):
    id: str
    name: str
    brand: Optional[str] = None
    model: Optional[str] = None
    specs: dict = {}
    configurations: List[ConfigOut] = []
