"""全流程陪伴与租后反馈 API schema。"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


class CompanionEventOut(BaseModel):
    id: str
    event_type: str
    title: str
    message: str
    payload: dict = Field(default_factory=dict)
    status: str
    created_at: datetime


class LogisticsOut(BaseModel):
    source: str
    carrier: Optional[str] = None
    tracking_no: Optional[str] = None
    status: str
    current_location: Optional[str] = None
    estimated_delivery: Optional[str] = None
    updated_at: Optional[str] = None
    notice: str


class DeviceGuideOut(BaseModel):
    camera_id: str
    name: str
    summary: str
    quick_start: List[str]
    setting_tips: List[str]
    guide_url: Optional[str] = None


class ReturnGuideOut(BaseModel):
    days_until_return: int
    message: str
    packing_tip: str
    outlet_query_url: str
    outlet_notice: str


class CompanionOut(BaseModel):
    order_id: str
    phase: str
    phase_label: str
    logistics: LogisticsOut
    device_guides: List[DeviceGuideOut]
    return_guide: ReturnGuideOut
    events: List[CompanionEventOut]
    feedback_submitted: bool


class FeedbackRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=1000)
    share_url: Optional[HttpUrl] = None
    showcase_allowed: bool = False

    @field_validator("showcase_allowed")
    @classmethod
    def sharing_requires_url(cls, value: bool, info):
        if value and not info.data.get("share_url"):
            raise ValueError("公开展示作品时必须提供作品链接")
        return value


class FeedbackOut(BaseModel):
    order_id: str
    rating: int
    comment: Optional[str] = None
    share_url: Optional[str] = None
    showcase_allowed: bool


class ShowcaseItem(BaseModel):
    camera_name: str
    rating: int
    comment: Optional[str] = None
    share_url: str
