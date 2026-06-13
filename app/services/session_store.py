"""会话存储 (Spec 6.1)。

抽象接口 + 进程内实现(带滑动 TTL)。MVP 不引入 Redis;
将来只需实现一个 RedisSessionStore 并在 get_session_store() 切换即可。

会话结构:
  {
    "session_id": str,
    "user_id": Optional[str],
    "round": int,
    "history": [{"role", "content"}],   # 最近若干轮
    "context": {...},                    # 当前订单草稿/已知实体
    "intents": [str],                    # 意图序列(用于漂移检测)
  }
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional

from app.config import settings

_TTL_SECONDS = settings.reservation_ttl_minutes * 60  # 复用 30 分钟
_MAX_HISTORY = 5  # 最近 5 轮


class InMemorySessionStore:
    def __init__(self, ttl_seconds: int = _TTL_SECONDS):
        self._data: Dict[str, dict] = {}
        self._expiry: Dict[str, float] = {}
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    def _expired(self, sid: str) -> bool:
        exp = self._expiry.get(sid)
        return exp is None or exp < time.time()

    def get(self, sid: str) -> Optional[dict]:
        with self._lock:
            if sid not in self._data or self._expired(sid):
                self._data.pop(sid, None)
                self._expiry.pop(sid, None)
                return None
            # 滑动过期
            self._expiry[sid] = time.time() + self._ttl
            return self._data[sid]

    def save(self, sid: str, session: dict) -> None:
        with self._lock:
            # 仅保留最近 N 轮历史
            if "history" in session:
                session["history"] = session["history"][-_MAX_HISTORY * 2 :]
            self._data[sid] = session
            self._expiry[sid] = time.time() + self._ttl

    def delete(self, sid: str) -> None:
        with self._lock:
            self._data.pop(sid, None)
            self._expiry.pop(sid, None)


_store: Optional[InMemorySessionStore] = None


def get_session_store() -> InMemorySessionStore:
    global _store
    if _store is None:
        _store = InMemorySessionStore()
    return _store
