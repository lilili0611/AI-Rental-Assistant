"""后台定时任务 (替代 Celery, MVP 用 APScheduler)。

- 每分钟扫描过期预留并释放占用 (Spec 3.2)。
- 每分钟扫描超时订单并自动取消释放占用。
- (Phase 2) 飞书轮询任务在 feishu_enabled 时启用。
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal
from app.services import order_service, reservation_service

logger = logging.getLogger("scheduler")
_scheduler: BackgroundScheduler = None


def _sweep_reservations():
    db = SessionLocal()
    try:
        n = reservation_service.sweep_expired(db)
        if n:
            logger.info("释放过期预留 %d 个", n)
    except Exception:  # noqa: BLE001
        logger.exception("预留扫描失败")
    finally:
        db.close()


def _sweep_orders():
    db = SessionLocal()
    try:
        stats = order_service.auto_cancel_stale_orders(db)
        if stats["total"]:
            logger.info(
                "自动取消超时订单 %d 个(未付款 %d, 商家未处理 %d)",
                stats["total"],
                stats["customer_unpaid"],
                stats["merchant_unprocessed"],
            )
    except Exception:  # noqa: BLE001
        logger.exception("超时订单扫描失败")
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    _scheduler.add_job(_sweep_reservations, "interval", minutes=1, id="sweep_reservations")
    _scheduler.add_job(_sweep_orders, "interval", minutes=1, id="sweep_orders")

    if settings.feishu_enabled:
        from app.integrations import feishu

        _scheduler.add_job(feishu.poll_changes_job, "interval", seconds=30, id="feishu_poll")
        logger.info("飞书轮询任务已启用")

    _scheduler.start()
    logger.info("定时任务已启动")
    return _scheduler


def shutdown_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
