"""Vercel Cron 入口。

Vercel 上不能依赖常驻后台进程, 因此把原本 APScheduler 做的扫描任务暴露成
受 CRON_SECRET 保护的 HTTP 端点, 由 Vercel Cron 定时调用。
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.database import SessionLocal
from app.services import order_service, reservation_service

router = APIRouter(prefix="/api/cron", tags=["cron"])


def _verify_cron_request(request: Request) -> None:
    secret = os.getenv("CRON_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET 未配置")
    if request.headers.get("authorization") != f"Bearer {secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/sweep")
def sweep(request: Request):
    _verify_cron_request(request)
    db = SessionLocal()
    try:
        expired_reservations = reservation_service.sweep_expired(db)
        cancelled_orders = order_service.auto_cancel_stale_orders(db)
    finally:
        db.close()

    feishu_polled = False
    if settings.feishu_enabled:
        from app.integrations import feishu

        feishu.poll_changes_job()
        feishu_polled = True

    return {
        "ok": True,
        "expired_reservations": expired_reservations,
        "cancelled_orders": cancelled_orders,
        "feishu_polled": feishu_polled,
    }
