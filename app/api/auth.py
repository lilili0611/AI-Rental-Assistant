"""认证 API。

租客侧: 邮箱 + 密码注册/登录, 写入 HttpOnly 会话 Cookie。
商家后台: 手机号 + 密码登录, 返回 Bearer token。
"""
from __future__ import annotations

import re
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import STAFF_ROLES
from app.config import settings
from app.core import security
from app.database import get_db
from app.models.user import User

router = APIRouter(prefix="/api/auth", tags=["auth"])
_CUSTOMER_COOKIE = "customer_session"
_CUSTOMER_SESSION_SECONDS = 12 * 3600


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("邮箱格式不正确")
    return email


def _email_phone_placeholder() -> str:
    return "email-" + secrets.token_hex(7)


def _set_customer_session(response: Response, user: User) -> None:
    response.set_cookie(
        _CUSTOMER_COOKIE,
        security.make_token(user.id, ttl_seconds=_CUSTOMER_SESSION_SECONDS),
        max_age=_CUSTOMER_SESSION_SECONDS,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def _customer_response(user: User) -> dict:
    return {
        "user_id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
    }


class PhoneLoginRequest(BaseModel):
    phone: str = Field(min_length=4, max_length=20)
    name: Optional[str] = None


class CustomerRegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=6, max_length=128)
    name: Optional[str] = Field(default=None, max_length=100)

    @field_validator("email")
    @classmethod
    def email_valid(cls, value: str) -> str:
        return _normalize_email(value)


class CustomerLoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def email_valid(cls, value: str) -> str:
        return _normalize_email(value)


class StaffLoginRequest(BaseModel):
    phone: str = Field(min_length=4, max_length=20)
    password: str = Field(min_length=1, max_length=128)


@router.post("/login")
def login(
    body: CustomerLoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """租客邮箱密码登录。"""
    user = db.execute(
        select(User).where(User.email == body.email)
    ).scalars().first()
    ok = (
        user is not None
        and user.role == "customer"
        and security.verify_password(body.password, user.password_hash)
    )
    if not ok:
        raise HTTPException(
            status_code=401,
            detail={"error": "邮箱或密码错误", "error_code": "invalid_credentials"},
        )
    _set_customer_session(response, user)
    return _customer_response(user)


@router.post("/register", status_code=201)
def register(
    body: CustomerRegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """租客邮箱密码注册。邮箱不做验证码校验。"""
    existing = db.execute(
        select(User).where(User.email == body.email)
    ).scalars().first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"error": "该邮箱已注册", "error_code": "email_exists"},
        )

    name = body.name or body.email.split("@", 1)[0]
    user = User(
        phone=_email_phone_placeholder(),
        email=body.email,
        name=name,
        role="customer",
        is_authenticated=True,
        password_hash=security.hash_password(body.password),
    )
    db.add(user)
    try:
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": "注册失败，请更换邮箱后重试", "error_code": "register_conflict"},
        )
    db.refresh(user)
    _set_customer_session(response, user)
    return _customer_response(user)


@router.post("/logout")
def logout(response: Response):
    """租客退出登录：清除浏览器会话 Cookie。"""
    response.delete_cookie(_CUSTOMER_COOKIE, path="/")
    return {"ok": True}


@router.post("/phone-login")
def phone_login(body: PhoneLoginRequest, db: Session = Depends(get_db)):
    """旧版手机号直登，仅保留给本地演示/兼容脚本；正式前端不使用。"""
    if not settings.enable_phone_login:
        raise HTTPException(
            status_code=404,
            detail={"error": "接口已关闭", "error_code": "disabled"},
        )
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
