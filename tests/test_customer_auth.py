"""租客邮箱账号密码认证测试。"""
from __future__ import annotations

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import select

from app.api import auth
from app.api.deps import get_current_user
from app.config import settings
from app.core import security
from app.models.user import User


def _cookie_value(response: Response) -> str:
    return response.headers["set-cookie"].split("customer_session=", 1)[1].split(";", 1)[0]


def test_customer_register_login_and_cookie_auth(db):
    register_response = Response()
    registered = auth.register(
        auth.CustomerRegisterRequest(
            email="NewUser@Example.COM", password="secret123", name="新用户"
        ),
        response=register_response,
        db=db,
    )

    assert registered["email"] == "newuser@example.com"
    assert "customer_session=" in register_response.headers["set-cookie"]
    user = db.execute(
        select(User).where(User.email == "newuser@example.com")
    ).scalars().one()
    assert user.password_hash != "secret123"
    assert security.verify_password("secret123", user.password_hash)

    login_response = Response()
    logged_in = auth.login(
        auth.CustomerLoginRequest(email="newuser@example.com", password="secret123"),
        response=login_response,
        db=db,
    )
    assert logged_in["user_id"] == user.id

    current = get_current_user(
        customer_session=_cookie_value(login_response), db=db
    )
    assert current.id == user.id


def test_customer_register_rejects_duplicate_email(db):
    body = auth.CustomerRegisterRequest(email="dupe@example.com", password="secret123")
    auth.register(body, response=Response(), db=db)

    with pytest.raises(HTTPException) as exc:
        auth.register(body, response=Response(), db=db)

    assert exc.value.status_code == 409


def test_customer_login_rejects_wrong_password(db):
    auth.register(
        auth.CustomerRegisterRequest(email="login@example.com", password="secret123"),
        response=Response(),
        db=db,
    )

    with pytest.raises(HTTPException) as exc:
        auth.login(
            auth.CustomerLoginRequest(email="login@example.com", password="bad"),
            response=Response(),
            db=db,
        )

    assert exc.value.status_code == 401


def test_customer_auth_requires_session_cookie(db, seeded):
    with pytest.raises(HTTPException) as exc:
        get_current_user(customer_session=None, db=db)

    assert exc.value.status_code == 401


def test_phone_login_disabled_by_default(db, monkeypatch):
    monkeypatch.setattr(settings, "enable_phone_login", False)

    with pytest.raises(HTTPException) as exc:
        auth.phone_login(auth.PhoneLoginRequest(phone="13800000001"), db=db)

    assert exc.value.status_code == 404


def test_phone_login_can_be_enabled_for_compat(db, monkeypatch):
    monkeypatch.setattr(settings, "enable_phone_login", True)

    result = auth.phone_login(auth.PhoneLoginRequest(phone="13800000001"), db=db)

    assert result["phone"] == "13800000001"
