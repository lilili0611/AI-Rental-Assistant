"""用户与地址模型。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class User(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "users"

    phone: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )
    name: Mapped[Optional[str]] = mapped_column(String(100))
    is_authenticated: Mapped[bool] = mapped_column(Boolean, default=False)
    # 敏感信息加密存储 (AES)
    id_number_encrypted: Mapped[Optional[str]] = mapped_column(String(255))
    address_encrypted: Mapped[Optional[str]] = mapped_column(String(255))
    # Phase 1/2 简化角色: customer / staff / admin
    # (枚举可扩展为 sales/warehouse/finance/service, 见 PRD 待决策项1)
    role: Mapped[str] = mapped_column(String(20), default="customer")
    credit_score: Mapped[int] = mapped_column(Integer, default=100)

    addresses: Mapped[list["UserAddress"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserAddress(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "user_addresses"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True, nullable=False
    )
    address_type: Mapped[str] = mapped_column(String(20), default="shipping")
    province: Mapped[Optional[str]] = mapped_column(String(50))
    city: Mapped[Optional[str]] = mapped_column(String(50))
    district: Mapped[Optional[str]] = mapped_column(String(50))
    detail_address: Mapped[Optional[str]] = mapped_column(String(500))
    receiver_name: Mapped[Optional[str]] = mapped_column(String(100))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship(back_populates="addresses")
