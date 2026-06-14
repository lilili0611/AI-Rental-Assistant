"""FastAPI 应用入口。

启动: uvicorn app.main:app --reload
文档: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import auth, cameras, chat, inventory, orders, pricing, reservations
from app.config import settings
from app.database import engine
from app.models import Base  # noqa: F401  导入即注册全部模型到 metadata
from app.scheduler import shutdown_scheduler, start_scheduler

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

logging.basicConfig(level=logging.INFO)


def _auto_seed_if_empty() -> None:
    """云端首次部署: 数据库为空时灌入演示目录。非空则不动(不会覆盖已有数据)。"""
    from app.database import SessionLocal
    from app.models.camera import Camera

    db = SessionLocal()
    try:
        if db.query(Camera).count() == 0:
            logging.info("AUTO_SEED: 数据库为空, 灌入演示目录…")
            from scripts.seed_data import seed

            seed()
        else:
            logging.info("AUTO_SEED: 数据库已有数据, 跳过。")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动: 建表 +(可选)自动灌种子 + 启动定时任务
    Base.metadata.create_all(bind=engine)
    if settings.auto_seed:
        _auto_seed_if_empty()
    start_scheduler()
    yield
    # 关闭
    shutdown_scheduler()


app = FastAPI(
    title="相机租赁 AI 助手",
    version=__version__,
    description="对接飞书数据、面向客户与内部员工的 AI 租赁管理助手 (Phase 1 + 2)",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(cameras.router)
app.include_router(inventory.router)
app.include_router(pricing.router)
app.include_router(chat.router)
app.include_router(reservations.router)
app.include_router(orders.router)


@app.get("/health", tags=["system"])
def health():
    return {
        "status": "ok",
        "version": __version__,
        "llm_enabled": settings.llm_enabled,
        "feishu_enabled": settings.feishu_enabled,
    }


# 租客下单前端 (静态页)
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


# 商家后台 (静态页，页面内用员工手机号登录，接口侧校验 staff 权限)
@app.get("/admin", include_in_schema=False)
def admin():
    return FileResponse(os.path.join(_STATIC_DIR, "admin.html"))


app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
