"""认证 API (MVP 简化版)。

PRD 要求手机号 + 短信验证码登录。MVP 暂不接短信，
用手机号直接"登录"：存在则返回，不存在则创建为 customer。
返回的 user_id 即前端要带的 X-User-Id。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import STAFF_ROLES
from app.core import security
from app.database import get_db
from app.models.user import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    phone: str = Field(min_length=4, max_length=20)
    name: Optional[str] = None


class StaffLoginRequest(BaseModel):
    phone: str = Field(min_length=4, max_length=20)
    password: str = Field(min_length=1, max_length=128)


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


@router.post("/staff-login")
def staff_login(body: StaffLoginRequest, db: Session = Depends(get_db)):
    """🆕 v2.2 商家后台登录: 手机号 + 密码 → 会话令牌。

    失败统一返回 401(不区分用户不存在/密码错/非员工), 避免信息泄露。
    """
    user = db.execute(
        select(User).where(User.phone == body.phone)
    ).scalars().first()
    ok = (
        user is not None
        and user.role in STAFF_ROLES
        and security.verify_password(body.password, user.password_hash)
    )
    if not ok:
        raise HTTPException(
            status_code=401,
            detail={"error": "手机号或密码错误", "error_code": "invalid_credentials"},
        )
    return {
        "token": security.make_token(user.id),
        "user_id": user.id,
        "name": user.name,
        "role": user.role,
    }
