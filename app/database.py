"""数据库引擎与会话管理。"""
from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


def _normalize_url(url: str) -> str:
    """让用户能直接粘贴 Supabase 原始连接串。

    Supabase 给的是 `postgresql://...`(或老式 `postgres://`), SQLAlchemy 需要
    显式驱动 `postgresql+psycopg://`, 这里自动补上, 省去手改。
    """
    if url.startswith("postgresql+") or url.startswith("postgresql+psycopg"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    return url


DATABASE_URL = _normalize_url(settings.database_url)
_is_sqlite = DATABASE_URL.startswith("sqlite")

# SQLite 需要 check_same_thread=False 以支持多线程(FastAPI + 定时任务)
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

# Postgres/Supabase: 池里空闲连接会被服务端回收, 用 pool_recycle 主动回收避免报错;
# pool_pre_ping 兜底失效连接。SQLite 无连接池概念, 不需要这些。
_engine_kwargs = {} if _is_sqlite else {"pool_recycle": 1800}

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    echo=False,
    **_engine_kwargs,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
