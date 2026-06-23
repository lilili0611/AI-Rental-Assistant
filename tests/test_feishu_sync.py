"""飞书同步补偿逻辑测试。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.integrations import feishu
from app.models.order import Order
from app.services import order_service


def test_should_sync_only_after_merchant_review(db, seeded):
    order = order_service.create_order(
        db,
        user_id=seeded["user"].id,
        items=[{"camera_config_id": seeded["config"].id, "quantity": 1}],
        rental_start=date(2024, 9, 1),
        rental_end=date(2024, 9, 3),
    )

    assert not feishu.should_sync_order(order)

    order = order_service.review_order(
        db,
        order,
        approve=True,
        operator_id=seeded["staff"].id,
        paid_amount=Decimal("270"),
    )

    assert feishu.should_sync_order(order)


def test_push_pending_orders_skips_unreviewed_orders(db, seeded, monkeypatch):
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

    assert feishu._push_pending_orders(db) == 0
    db.expire_all()
    assert db.get(Order, order.id).sync_status == "none"
    assert pushed_ids == []


def test_push_pending_orders_retries_reviewed_orders(db, seeded, monkeypatch):
    order = order_service.create_order(
        db,
        user_id=seeded["user"].id,
        items=[{"camera_config_id": seeded["config"].id, "quantity": 1}],
        rental_start=date(2024, 9, 1),
        rental_end=date(2024, 9, 3),
    )
    order = order_service.review_order(
        db,
        order,
        approve=True,
        operator_id=seeded["staff"].id,
        paid_amount=Decimal("270"),
    )
    order.sync_status = "sync_pending"
    db.commit()

    pushed_ids = []
    monkeypatch.setattr(feishu, "push_order", lambda o: pushed_ids.append(o.id) or True)

    assert feishu._push_pending_orders(db) == 1
    db.expire_all()
    assert db.get(Order, order.id).sync_status == "synced"
    assert pushed_ids == [order.id]


def test_cancelled_order_syncs_only_if_previously_synced(db, seeded):
    order = order_service.create_order(
        db,
        user_id=seeded["user"].id,
        items=[{"camera_config_id": seeded["config"].id, "quantity": 1}],
        rental_start=date(2024, 9, 1),
        rental_end=date(2024, 9, 3),
    )
    order.status = "cancelled"
    order.sync_status = "none"
    assert not feishu.should_sync_order(order)

    order.sync_status = "synced"
    assert feishu.should_sync_order(order)
