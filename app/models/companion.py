"""全流程陪伴事件、租后评价与自愿作品分享。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class CompanionEvent(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "companion_events"
    __table_args__ = (
        UniqueConstraint("order_id", "event_type", name="uq_companion_order_event"),
    )

    order_id: Mapped[str] = mapped_column(
        String(30), ForeignKey("orders.id"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True, nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="unread", index=True)


class OrderFeedback(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "order_feedback"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_feedback_order"),
    )

    order_id: Mapped[str] = mapped_column(
        String(30), ForeignKey("orders.id"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True, nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(String(1000))
    share_url: Mapped[Optional[str]] = mapped_column(String(1000))
    showcase_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
