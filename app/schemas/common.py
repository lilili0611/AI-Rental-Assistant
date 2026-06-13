"""通用响应 schema。"""
from __future__ import annotations

from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Pagination(BaseModel):
    total: int
    page: int
    limit: int
    pages: int


class ErrorResponse(BaseModel):
    error: str
    details: Optional[str] = None
    error_code: Optional[str] = None
