"""认证 API。

租客侧: 邮箱 + 密码注册/登录, 写入 HttpOnly 会话 Cookie。
商家后台: 手机号 + 密码登录, 返回 Bearer token。
"""
from __future__ import annotations

import base64
import binascii
import re
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import STAFF_ROLES, get_current_user
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
        "avatar_data": user.avatar_data,
    }


_AVATAR_RE = re.compile(
    r"^data:image/(?P<kind>jpeg|png|webp);base64,(?P<data>[A-Za-z0-9+/=]+)$"
)
_MAX_AVATAR_BYTES = 300 * 1024
_MAX_AVATAR_DATA_LENGTH = 450_000


def _normalize_avatar_data(value: str) -> Optional[str]:
    value = (value or "").strip()
    if not value:
        return None
    if len(value) > _MAX_AVATAR_DATA_LENGTH:
        raise ValueError("头像文件过大，请重新选择")
    match = _AVATAR_RE.fullmatch(value)
    if not match:
        raise ValueError("头像仅支持 JPEG、PNG 或 WebP 图片")
    try:
        raw = base64.b64decode(match.group("data"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("头像图片格式无效") from exc
    if not raw or len(raw) > _MAX_AVATAR_BYTES:
        raise ValueError("头像文件过大，请重新选择")
    kind = match.group("kind")
    valid_magic = (
        (kind == "jpeg" and raw.startswith(b"\xff\xd8\xff"))
        or (kind == "png" and raw.startswith(b"\x89PNG\r\n\x1a\n"))
        or (kind == "webp" and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP")
    )
    if not valid_magic:
        raise ValueError("头像图片内容与格式不匹配")
    return value


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


class CustomerProfileUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    email: Optional[str] = Field(default=None, min_length=5, max_length=255)
    avatar_data: Optional[str] = Field(default=None, max_length=_MAX_AVATAR_DATA_LENGTH)
    current_password: Optional[str] = Field(default=None, max_length=128)


class CustomerPasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


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


@router.get("/me")
def get_profile(user: User = Depends(get_current_user)):
    """读取当前租客资料，不接受外部 user_id。"""
    return _customer_response(user)


@router.patch("/me")
def update_profile(
    body: CustomerProfileUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新当前租客昵称、邮箱或头像。邮箱变更需要当前密码。"""
    changed = False
    fields = body.model_fields_set

    if "name" in fields:
        name = (body.name or "").strip()
        if not name:
            raise HTTPException(
                status_code=422,
                detail={"error": "昵称不能为空", "error_code": "invalid_name"},
            )
        user.name = name
        changed = True

    if "email" in fields:
        try:
            email = _normalize_email(body.email or "")
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": str(exc), "error_code": "invalid_email"},
            ) from exc
        if email != user.email:
            if not security.verify_password(body.current_password or "", user.password_hash):
                raise HTTPException(
                    status_code=401,
                    detail={"error": "当前密码错误", "error_code": "invalid_credentials"},
                )
            existing = db.execute(
                select(User).where(User.email == email, User.id != user.id)
            ).scalars().first()
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail={"error": "该邮箱已被使用", "error_code": "email_exists"},
                )
            user.email = email
            changed = True

    if "avatar_data" in fields:
        try:
            user.avatar_data = _normalize_avatar_data(body.avatar_data or "")
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": str(exc), "error_code": "invalid_avatar"},
            ) from exc
        changed = True

    if changed:
        db.commit()
        db.refresh(user)
    return _customer_response(user)


@router.post("/change-password")
def change_password(
    body: CustomerPasswordChangeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """当前密码校验通过后更新为新的加盐哈希。"""
    if not security.verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail={"error": "当前密码错误", "error_code": "invalid_credentials"},
        )
    if security.verify_password(body.new_password, user.password_hash):
        raise HTTPException(
            status_code=422,
            detail={"error": "新密码不能与当前密码相同", "error_code": "password_unchanged"},
        )
    user.password_hash = security.hash_password(body.new_password)
    db.commit()
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
