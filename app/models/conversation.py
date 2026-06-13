"""对话记录模型。"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import ForeignKey, Integer, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Conversation(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "conversations"

    session_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id")
    )
    round_number: Mapped[int] = mapped_column(Integer, default=1)
    user_message: Mapped[Optional[str]] = mapped_column(String(1000))
    ai_response: Mapped[Optional[str]] = mapped_column(String(2000))
    detected_intent: Mapped[Optional[str]] = mapped_column(String(50))
    intent_confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 3))
    entities: Mapped[dict] = mapped_column(JSON, default=dict)
