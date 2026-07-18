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


def test_customer_can_read_and_update_own_profile(db):
    auth.register(
        auth.CustomerRegisterRequest(
            email="profile@example.com", password="secret123", name="旧昵称"
        ),
        response=Response(),
        db=db,
    )
    user = db.execute(
        select(User).where(User.email == "profile@example.com")
    ).scalars().one()
    avatar = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )

    before = auth.get_profile(user=user)
    assert before["user_id"] == user.id
    assert before["avatar_data"] is None

    updated = auth.update_profile(
        auth.CustomerProfileUpdateRequest(name="新昵称", avatar_data=avatar),
        db=db,
        user=user,
    )
    assert updated["name"] == "新昵称"
    assert updated["avatar_data"] == avatar


def test_customer_email_change_requires_current_password_and_uniqueness(db):
    for email in ("first@example.com", "second@example.com"):
        auth.register(
            auth.CustomerRegisterRequest(email=email, password="secret123"),
            response=Response(),
            db=db,
        )
    user = db.execute(
        select(User).where(User.email == "first@example.com")
    ).scalars().one()

    with pytest.raises(HTTPException) as exc:
        auth.update_profile(
            auth.CustomerProfileUpdateRequest(email="new@example.com"),
            db=db,
            user=user,
        )
    assert exc.value.status_code == 401

    changed = auth.update_profile(
        auth.CustomerProfileUpdateRequest(
            email="NEW@example.com", current_password="secret123"
        ),
        db=db,
        user=user,
    )
    assert changed["email"] == "new@example.com"

    with pytest.raises(HTTPException) as exc:
        auth.update_profile(
            auth.CustomerProfileUpdateRequest(
                email="second@example.com", current_password="secret123"
            ),
            db=db,
            user=user,
        )
    assert exc.value.status_code == 409


def test_customer_password_change_verifies_current_and_hashes_new_password(db):
    auth.register(
        auth.CustomerRegisterRequest(email="password@example.com", password="secret123"),
        response=Response(),
        db=db,
    )
    user = db.execute(
        select(User).where(User.email == "password@example.com")
    ).scalars().one()
    old_hash = user.password_hash

    with pytest.raises(HTTPException) as exc:
        auth.change_password(
            auth.CustomerPasswordChangeRequest(
                current_password="wrong", new_password="newSecret456"
            ),
            db=db,
            user=user,
        )
    assert exc.value.status_code == 401

    result = auth.change_password(
        auth.CustomerPasswordChangeRequest(
            current_password="secret123", new_password="newSecret456"
        ),
        db=db,
        user=user,
    )
    assert result == {"ok": True}
    assert user.password_hash != old_hash
    assert security.verify_password("newSecret456", user.password_hash)
    assert not security.verify_password("secret123", user.password_hash)


def test_customer_profile_rejects_spoofed_avatar_content(db):
    auth.register(
        auth.CustomerRegisterRequest(email="avatar@example.com", password="secret123"),
        response=Response(),
        db=db,
    )
    user = db.execute(
        select(User).where(User.email == "avatar@example.com")
    ).scalars().one()

    with pytest.raises(HTTPException) as exc:
        auth.update_profile(
            auth.CustomerProfileUpdateRequest(
                avatar_data="data:image/png;base64,aGVsbG8="
            ),
            db=db,
            user=user,
        )
    assert exc.value.status_code == 422
