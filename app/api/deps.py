"""API 依赖: 认证与权限 (Spec 6.3)。

MVP 认证: 请求头 X-User-Id 标识用户(真实短信验证码登录后续接入)。
权限: C 端只能操作自己的数据; B 端 staff/admin 可查看全部。
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User


def get_optional_user(
    x_user_id: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """可选用户(匿名查询允许)。"""
    if not x_user_id:
        return None
    return db.get(User, x_user_id)


def get_current_user(
    x_user_id: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """必须认证。order_* 系列接口使用。"""
    if not x_user_id:
        raise HTTPException(
            status_code=401,
            detail={"error": "未认证", "error_code": "unauthorized",
                    "details": "请在请求头 X-User-Id 携带用户标识"},
        )
    user = db.get(User, x_user_id)
    if not user:
        raise HTTPException(
            status_code=401,
            detail={"error": "用户不存在", "error_code": "unauthorized"},
        )
    return user


def is_staff(user: User) -> bool:
    return user.role in ("staff", "admin", "sales", "warehouse", "finance", "service")
