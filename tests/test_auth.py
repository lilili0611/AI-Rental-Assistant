"""v2.2 后台鉴权: 口令哈希 + 会话令牌。"""
from __future__ import annotations

import time

from app.core import security


def test_password_hash_roundtrip():
    h = security.hash_password("admin888")
    assert h != "admin888"  # 不存明文
    assert h.startswith("pbkdf2_sha256$")
    assert security.verify_password("admin888", h)
    assert not security.verify_password("wrong", h)


def test_password_hash_is_salted():
    """同一口令两次哈希应不同(加盐), 但都能校验通过。"""
    h1 = security.hash_password("same")
    h2 = security.hash_password("same")
    assert h1 != h2
    assert security.verify_password("same", h1)
    assert security.verify_password("same", h2)


def test_verify_password_handles_garbage():
    assert not security.verify_password("x", "")
    assert not security.verify_password("x", None)
    assert not security.verify_password("x", "not-a-valid-hash")


def test_token_roundtrip():
    tok = security.make_token("user-123")
    assert security.verify_token(tok) == "user-123"


def test_token_tampered_rejected():
    tok = security.make_token("user-123")
    # 篡改用户名部分, 签名不再匹配
    bad = "hacker." + tok.split(".", 1)[1]
    assert security.verify_token(bad) is None
    assert security.verify_token("garbage") is None
    assert security.verify_token("") is None


def test_token_expired_rejected():
    tok = security.make_token("user-123", ttl_seconds=-1)
    assert security.verify_token(tok) is None


def test_token_signature_depends_on_key():
    """改密钥后旧令牌应失效(防伪造)。"""
    tok = security.make_token("user-123")
    from app.config import settings
    old = settings.encryption_key
    try:
        settings.encryption_key = old + "-changed"
        assert security.verify_token(tok) is None
    finally:
        settings.encryption_key = old
    assert security.verify_token(tok) == "user-123"
