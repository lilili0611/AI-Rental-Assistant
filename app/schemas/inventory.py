"""库存与价格 schema (Spec 4.2 / 4.3)。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List

from pydantic import BaseModel


class DayAvailabilityOut(BaseModel):
    date: date
    available: int


class ConfigAvailabilityOut(BaseModel):
    config_id: str
    config_name: str
    total_units: int
    min_available_in_range: int
    daily_breakdown: List[DayAvailabilityOut]


class AvailabilityResponse(BaseModel):
    query: dict
    results: List[ConfigAvailabilityOut]


class PricingResponse(BaseModel):
    device: str
    rental_period: dict
    pricing: dict
    deposit: Decimal
    total_due: Decimal
