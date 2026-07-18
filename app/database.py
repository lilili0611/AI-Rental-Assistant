"""数据库引擎与会话管理。"""
from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine, inspect, text
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


def ensure_runtime_schema() -> None:
    """补齐轻量上线迁移，覆盖 create_all 不会修改既有表的场景。"""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if "users" not in tables:
        return

    user_columns = {col["name"] for col in inspector.get_columns("users")}
    with engine.begin() as conn:
        if "email" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(255)"))
        if "avatar_data" not in user_columns:
            statement = (
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_data TEXT"
                if engine.dialect.name == "postgresql"
                else "ALTER TABLE users ADD COLUMN avatar_data TEXT"
            )
            conn.execute(text(statement))

        if engine.dialect.name == "postgresql":
            conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)")
            )
        else:
            conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)")
            )

        # v2.6 起押金只展示不计入应付。历史订单若仍是「租金+押金」口径,
        # 且能明确识别为旧值, 自动迁到「应付=租金」。
        if "orders" in tables:
            conn.execute(
                text(
                    "UPDATE orders "
                    "SET total_price = subtotal "
                    "WHERE total_price = subtotal + deposit_amount"
                )
            )
