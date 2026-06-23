"""飞书同步补偿逻辑测试。"""
from __future__ import annotations

from datetime import date

from app.integrations import feishu
from app.models.order import Order
from app.services import order_service


def test_push_pending_orders_retries_local_sync_pending(db, seeded, monkeypatch):
    order = order_service.create_order(
        db,
        user_id=seeded["user"].id,
        items=[{"camera_config_id": seeded["config"].id, "quantity": 1}],
        rental_start=date(2024, 9, 1),
        rental_end=date(2024, 9, 3),
    )
    order.sync_status = "sync_pending"
    db.commit()

    pushed_ids = []
    monkeypatch.setattr(feishu, "push_order", lambda o: pushed_ids.append(o.id) or True)

    assert feishu._push_pending_orders(db) == 1
    db.expire_all()
    assert db.get(Order, order.id).sync_status == "synced"
    assert pushed_ids == [order.id]
