"""敏感字段加密 + 后台口令哈希 + 会话令牌 (纯标准库)。

- 字段加密(身份证/地址): MVP 占位实现, 生产应换 AES-256-GCM。
- 🆕 v2.2 口令哈希: PBKDF2-HMAC-SHA256 加盐, 用于商家后台登录。
- 🆕 v2.2 会话令牌: HMAC-SHA256 签名 + 有效期, 无状态, 后台接口鉴权用。
  签名密钥统一用 ENCRYPTION_KEY, 因此生产务必设置强随机的 ENCRYPTION_KEY。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

from app.config import settings


def _key() -> bytes:
    return hashlib.sha256(settings.encryption_key.encode("utf-8")).digest()


# ============ v2.2 口令哈希 (PBKDF2) ============
_PBKDF2_ROUNDS = 200_000


def hash_password(password: str) -> str:
    """生成加盐口令哈希, 格式 'pbkdf2_sha256$rounds$salt_hex$hash_hex'。"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验明文口令是否匹配存储的哈希。任何异常视为不匹配。"""
    if not stored:
        return False
    try:
        algo, rounds, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# ============ v2.2 会话令牌 (HMAC 签名 + 有效期) ============
def _sign(msg: str) -> str:
    return hmac.new(_key(), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def make_token(user_id: str, ttl_seconds: int = 12 * 3600) -> str:
    """签发会话令牌: 载荷含 user_id 与过期时间戳, 末尾附 HMAC 签名。"""
    exp = int(time.time()) + ttl_seconds
    payload = f"{user_id}.{exp}"
    return f"{payload}.{_sign(payload)}"


def verify_token(token: str):
    """校验令牌, 通过返回 user_id, 否则返回 None。"""
    if not token:
        return None
    try:
        user_id, exp_str, sig = token.rsplit(".", 2)
    except ValueError:
        return None
    payload = f"{user_id}.{exp_str}"
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        if int(exp_str) < int(time.time()):
            return None
    except ValueError:
        return None
    return user_id


def encrypt(plaintext: str) -> str:
    """加密(占位实现: XOR 流 + HMAC 完整性)。生产请换 AES-256-GCM。"""
    if plaintext is None:
        return None
    key = _key()
    data = plaintext.encode("utf-8")
    keystream = (key * (len(data) // len(key) + 1))[: len(data)]
    cipher = bytes(b ^ k for b, k in zip(data, keystream))
    tag = hmac.new(key, cipher, hashlib.sha256).digest()[:16]
    return base64.b64encode(tag + cipher).decode("ascii")


def decrypt(token: str) -> str:
    if token is None:
        return None
    key = _key()
    raw = base64.b64decode(token)
    tag, cipher = raw[:16], raw[16:]
    expected = hmac.new(key, cipher, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expected):
        raise ValueError("密文完整性校验失败")
    keystream = (key * (len(cipher) // len(key) + 1))[: len(cipher)]
    data = bytes(b ^ k for b, k in zip(cipher, keystream))
    return data.decode("utf-8")
