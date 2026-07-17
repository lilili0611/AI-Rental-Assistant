"""Vercel Cron 入口测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import cron as cron_module
from app.config import settings
from app.main import app


client = TestClient(app)


def test_cron_requires_secret_when_missing(monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)

    response = client.get("/api/cron/sweep")

    assert response.status_code == 503


def test_cron_rejects_wrong_secret(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "expected-secret")

    response = client.get(
        "/api/cron/sweep",
        headers={"authorization": "Bearer wrong-secret"},
    )

    assert response.status_code == 401


def test_cron_runs_with_valid_secret(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "expected-secret")
    monkeypatch.setattr(settings, "feishu_enabled", False)

    class DummyDB:
        def close(self):
            pass

    monkeypatch.setattr(cron_module, "SessionLocal", lambda: DummyDB())
    monkeypatch.setattr(cron_module.reservation_service, "sweep_expired", lambda db: 2)
    monkeypatch.setattr(
        cron_module.order_service,
        "auto_cancel_stale_orders",
        lambda db: {"customer_unpaid": 1, "merchant_unprocessed": 0, "total": 1},
    )
    monkeypatch.setattr(
        cron_module.companion_service,
        "sweep_events",
        lambda db: {"orders_scanned": 3, "events_created": 2},
    )

    response = client.get(
        "/api/cron/sweep",
        headers={"authorization": "Bearer expected-secret"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["expired_reservations"] == 2
    assert response.json()["cancelled_orders"]["total"] == 1
    assert response.json()["companion_events"]["events_created"] == 2
