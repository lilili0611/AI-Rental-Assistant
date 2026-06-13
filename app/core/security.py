"""敏感字段加密 (PRD 非功能需求: 身份证/地址 AES-256)。

MVP 用基于 ENCRYPTION_KEY 的对称加密。为避免引入额外依赖,
这里用标准库 hashlib 派生密钥 + 简单的可逆变换占位。
⚠️ 生产环境应替换为 cryptography 库的 AES-256-GCM。
"""
from __future__ import annotations

import base64
import hashlib
import hmac

from app.config import settings


def _key() -> bytes:
    return hashlib.sha256(settings.encryption_key.encode("utf-8")).digest()


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
