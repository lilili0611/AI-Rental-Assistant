"""订单流程测试 (Spec §9.3-9.7)。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.reservation import Reservation
from app.services import order_service, reservation_service
from app.services.order_service import ConflictError, OrderError


def _create_order(db, seeded, qty=1):
    return order_service.create_order(
        db,
        user_id=seeded["user"].id,
        items=[{"camera_config_id": seeded["config"].id, "quantity": qty}],
        rental_start=date(2024, 9, 1),
        rental_end=date(2024, 9, 3),
    )


def test_create_order_pending_payment(db, seeded):
    order = _create_order(db, seeded)
    assert order.status == "pending_payment"
    # 3 天 = 三天档价 270 (conftest), 单台
    assert order.total_price == Decimal("270.00")
    assert order.deposit_amount == Decimal("2000.00")


def test_manual_payment_confirmation(db, seeded):
    """🔴 §9.7: 人工确认收款 pending_payment -> paid, 无自动支付。"""
    order = _create_order(db, seeded)
    order = order_service.confirm_payment(
        db, order, paid_amount=Decimal("2810"),
        payment_note="转账流水 123", operator_id=seeded["staff"].id,
    )
    assert order.status == "paid"
    assert order.paid_amount == Decimal("2810.00")
    assert order.payment_note == "转账流水 123"


def test_illegal_transition_rejected(db, seeded):
    """§9.4: shipped 不能直接取消; pending 不能直接 shipped。"""
    order = _create_order(db, seeded)
    with pytest.raises(OrderError) as exc:
        order_service.advance_status(db, order, "shipped", operator_id=seeded["staff"].id)
    assert exc.value.code == "invalid_transition"


def test_full_lifecycle(db, seeded):
    order = _create_order(db, seeded)
    s = seeded["staff"].id
    order = order_service.confirm_payment(db, order, Decimal("2810"), "ok", s)
    order = order_service.advance_status(db, order, "confirmed", s)
    order = order_service.advance_status(db, order, "shipped", s)
    order = order_service.advance_status(db, order, "active", s)
    order = order_service.advance_status(db, order, "returned", s)
    order = order_service.advance_status(db, order, "completed", s)
    assert order.status == "completed"


def test_optimistic_lock_conflict(db, seeded):
    """§9.5: version 不匹配应拦截。"""
    order = _create_order(db, seeded)
    with pytest.raises(ConflictError):
        order_service.confirm_payment(
            db, order, Decimal("2810"), "x", seeded["staff"].id, version=999
        )


def test_cancel_unpaid_free(db, seeded):
    order = _create_order(db, seeded)
    result = order_service.cancel_order(db, order, operator_id=seeded["user"].id)
    assert result["status"] == "cancelled"
    assert result["cancellation_fee"] == Decimal("0.00")


def test_cancel_paid_charges_fee(db, seeded):
    order = _create_order(db, seeded)
    order = order_service.confirm_payment(db, order, Decimal("2270"), "ok", seeded["staff"].id)
    result = order_service.cancel_order(db, order, operator_id=seeded["user"].id)
    # 手续费 = total_price(270) * 10% = 27
    assert result["cancellation_fee"] == Decimal("27.00")
    # 退款 = 已付 2270 - 27 = 2243
    assert result["refund_amount"] == Decimal("2243.00")


def test_cancel_releases_inventory(db, seeded):
    """取消后库存应回归。"""
    from app.services import inventory_service
    order = _create_order(db, seeded, qty=3)
    a = inventory_service.get_config_availability(db, seeded["config"], date(2024, 9, 1), date(2024, 9, 3))
    assert a.min_available_in_range == 0
    order_service.cancel_order(db, order, operator_id=seeded["user"].id)
    a2 = inventory_service.get_config_availability(db, seeded["config"], date(2024, 9, 1), date(2024, 9, 3))
    assert a2.min_available_in_range == 3


def test_reservation_expiry_releases(db, seeded):
    """§9.3: 预留过期后占用自动释放。"""
    from app.services import inventory_service
    r = reservation_service.create_reservation(
        db, seeded["config"], 3, date(2024, 9, 1), date(2024, 9, 3)
    )
    db.commit()
    a = inventory_service.get_config_availability(db, seeded["config"], date(2024, 9, 1), date(2024, 9, 3))
    assert a.min_available_in_range == 0

    # 手动把过期时间提前, 触发扫描
    r.expires_at = datetime.now() - timedelta(minutes=1)
    db.commit()
    released = reservation_service.sweep_expired(db)
    assert released == 1
    a2 = inventory_service.get_config_availability(db, seeded["config"], date(2024, 9, 1), date(2024, 9, 3))
    assert a2.min_available_in_range == 3


def test_reservation_to_order_no_double_count(db, seeded):
    """预留转单不应重复占用库存。"""
    from app.services import inventory_service
    r = reservation_service.create_reservation(
        db, seeded["config"], 3, date(2024, 9, 1), date(2024, 9, 3)
    )
    db.commit()
    order = order_service.create_order(
        db,
        user_id=seeded["user"].id,
        items=[{"camera_config_id": seeded["config"].id, "quantity": 3}],
        rental_start=date(2024, 9, 1),
        rental_end=date(2024, 9, 3),
        reservation_id=r.id,
    )
    # 转单后仍是占满 3 台(而不是 6 台导致报错)
    a = inventory_service.get_config_availability(db, seeded["config"], date(2024, 9, 1), date(2024, 9, 3))
    assert a.min_available_in_range == 0
    db.refresh(r)
    assert r.status == "confirmed"
    assert r.order_id == order.id
