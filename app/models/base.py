"""ORM 基类与通用 mixin。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有模型的声明式基类。"""


def gen_uuid() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    """统一的创建/更新时间戳。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UUIDPKMixin:
    """UUID 字符串主键(SQLite 无原生 UUID，统一用 String(36))。"""

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=gen_uuid
    )
