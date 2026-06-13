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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动: 建表 + 启动定时任务
    Base.metadata.create_all(bind=engine)
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


app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
