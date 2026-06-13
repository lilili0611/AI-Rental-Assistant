"""认证 API (MVP 简化版)。

PRD 要求手机号 + 短信验证码登录。MVP 暂不接短信，
用手机号直接"登录"：存在则返回，不存在则创建为 customer。
返回的 user_id 即前端要带的 X-User-Id。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    phone: str = Field(min_length=4, max_length=20)
    name: Optional[str] = None


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.execute(
        select(User).where(User.phone == body.phone)
    ).scalars().first()
    if not user:
        user = User(
            phone=body.phone,
            name=body.name or f"租客{body.phone[-4:]}",
            role="customer",
            is_authenticated=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return {
        "user_id": user.id,
        "phone": user.phone,
        "name": user.name,
        "role": user.role,
    }
