"""后台定时任务 (替代 Celery, MVP 用 APScheduler)。

- 每分钟扫描过期预留并释放占用 (Spec 3.2)。
- (Phase 2) 飞书轮询任务在 feishu_enabled 时启用。
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal
from app.services import reservation_service

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


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    _scheduler.add_job(_sweep_reservations, "interval", minutes=1, id="sweep_reservations")

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
