"""订单流程测试 (Spec §9.3-9.7)。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.order import Order, OrderChange
from app.models.reservation import Reservation
from app.models.user import User
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
    assert order.subtotal == Decimal("270.00")
    assert order.deposit_amount == Decimal("2000.00")
    assert order.total_price == Decimal("270.00")


def test_create_order_rejects_empty_items(db, seeded):
    with pytest.raises(OrderError) as exc:
        order_service.create_order(
            db,
            user_id=seeded["user"].id,
            items=[],
            rental_start=date(2024, 9, 1),
            rental_end=date(2024, 9, 3),
        )

    assert exc.value.code == "empty_order"


def test_generate_order_id_retries_random_suffix_collision(db, seeded, monkeypatch):
    class FixedDatetime:
        @classmethod
        def now(cls):
            return datetime(2024, 9, 1, 12, 0, 0)

    values = iter([1, 1, 2])
    monkeypatch.setattr(order_service, "datetime", FixedDatetime)
    monkeypatch.setattr(order_service.secrets, "randbelow", lambda _: next(values))

    db.add(Order(
        id="ORD202409011200000001",
        user_id=seeded["user"].id,
        rental_start=date(2024, 9, 1),
        rental_end=date(2024, 9, 3),
    ))
    db.commit()

    assert order_service.generate_order_id(db) == "ORD202409011200000002"


def test_manual_payment_confirmation(db, seeded):
    """🔴 §9.7: 人工确认收款 pending_payment -> paid, 无自动支付。"""
    order = _create_order(db, seeded)
    order = order_service.confirm_payment(
        db, order, paid_amount=Decimal("270"),
        payment_note="转账流水 123", operator_id=seeded["staff"].id,
    )
    assert order.status == "paid"
    assert order.paid_amount == Decimal("270.00")
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
    order = order_service.confirm_payment(db, order, Decimal("270"), "ok", s)
    order = order_service.advance_status(db, order, "confirmed", s)
    order = order_service.advance_status(db, order, "shipped", s)
    order = order_service.advance_status(db, order, "active", s)
    order = order_service.advance_status(db, order, "returned", s)
    order = order_service.advance_status(db, order, "completed", s)
    assert order.status == "completed"


def test_review_approve_advances_to_confirmed(db, seeded):
    """🆕 v2.1 §9.8: 审核通过一步推进到 confirmed 并记录收款。"""
    order = _create_order(db, seeded)
    order = order_service.review_order(
        db, order, approve=True, operator_id=seeded["staff"].id,
        paid_amount=Decimal("270"), payment_note="微信转账",
    )
    assert order.status == "confirmed"
    assert order.paid_amount == Decimal("270.00")
    assert order.payment_note == "微信转账"
    assert order_service.display_status(order) == "已确认档期（待发货）"


def test_review_reject_stays_pending(db, seeded):
    """🆕 v2.1 §9.8: 驳回留在 pending_payment 并写 review_note。"""
    order = _create_order(db, seeded)
    order = order_service.review_order(
        db, order, approve=False, operator_id=seeded["staff"].id,
        review_note="未收到款",
    )
    assert order.status == "pending_payment"
    assert order.review_note == "未收到款"
    assert "审核未通过：未收到款" in order_service.display_status(order)


def test_review_only_from_pending(db, seeded):
    """🆕 v2.1: 非 pending_payment 不可审核。"""
    order = _create_order(db, seeded)
    order_service.review_order(db, order, approve=True, operator_id=seeded["staff"].id,
                              paid_amount=Decimal("270"))
    with pytest.raises(OrderError) as exc:
        order_service.review_order(db, order, approve=True, operator_id=seeded["staff"].id)
    assert exc.value.code == "invalid_transition"


def test_ship_requires_logistics(db, seeded):
    """🆕 v2.1 §9.9: 发货必须带快递公司+单号。"""
    order = _create_order(db, seeded)
    order = order_service.review_order(db, order, approve=True,
                                       operator_id=seeded["staff"].id, paid_amount=Decimal("270"))
    with pytest.raises(OrderError) as exc:
        order_service.ship_order(db, order, carrier="", tracking_no="",
                                 operator_id=seeded["staff"].id)
    assert exc.value.code == "missing_logistics"


def test_ship_then_accept_completes(db, seeded):
    """🆕 v2.1 §9.9: 发货写物流 -> shipped, 验收直接 -> completed(跳过 active/returned)。"""
    s = seeded["staff"].id
    order = _create_order(db, seeded)
    order = order_service.review_order(db, order, approve=True, operator_id=s,
                                       paid_amount=Decimal("270"))
    order = order_service.ship_order(db, order, carrier="顺丰速运",
                                     tracking_no="SF123", operator_id=s)
    assert order.status == "shipped"
    assert order.carrier == "顺丰速运"
    assert order.tracking_no == "SF123"
    assert order_service.display_status(order) == "已发货"

    order = order_service.accept_order(db, order, operator_id=s)
    assert order.status == "completed"
    assert order_service.display_status(order) == "订单已完结"


def test_display_status_mapping(db, seeded):
    """🆕 v2.1 §9.10: 内部状态映射到正确中文标签。"""
    order = _create_order(db, seeded)
    assert order_service.display_status(order) == "商家审核中"


def test_optimistic_lock_conflict(db, seeded):
    """§9.5: version 不匹配应拦截。"""
    order = _create_order(db, seeded)
    with pytest.raises(ConflictError):
        order_service.confirm_payment(
            db, order, Decimal("270"), "x", seeded["staff"].id, version=999
        )


def test_confirm_payment_rejects_underpaid_rent(db, seeded):
    order = _create_order(db, seeded)
    with pytest.raises(OrderError) as exc:
        order_service.confirm_payment(
            db, order, Decimal("269.99"), "x", seeded["staff"].id
        )
    assert exc.value.code == "underpaid"


def test_cancel_unpaid_free(db, seeded):
    order = _create_order(db, seeded)
    result = order_service.cancel_order(db, order, operator_id=seeded["user"].id)
    assert result["status"] == "cancelled"
    assert result["cancellation_fee"] == Decimal("0.00")


def test_cancel_paid_charges_fee(db, seeded):
    order = _create_order(db, seeded)
    order = order_service.confirm_payment(db, order, Decimal("270"), "ok", seeded["staff"].id)
    result = order_service.cancel_order(db, order, operator_id=seeded["user"].id)
    # 手续费只按租金 subtotal(270) * 10%; 押金未通过平台支付
    assert result["cancellation_fee"] == Decimal("27.00")
    # 退款 = 已付租金 270 - 27 = 243
    assert result["refund_amount"] == Decimal("243.00")


def test_extend_order_keeps_total_price_as_rent_only(db, seeded):
    order = _create_order(db, seeded)

    result = order_service.extend_order(
        db,
        order,
        new_end_date=date(2024, 9, 5),
        operator_id=seeded["user"].id,
        version=order.version,
    )

    # 5 天租金 = 270 + 2 * 80 = 430; 押金只展示, 不计入应付
    assert result["total_price"] == Decimal("430.00")
    assert result["price_diff"] == Decimal("160.00")


def test_staff_can_update_order_rent_before_review(db, seeded):
    order = _create_order(db, seeded)

    order = order_service.update_order_rent(
        db,
        order,
        rent_amount=Decimal("250"),
        operator_id=seeded["staff"].id,
        version=order.version,
        reason="线下议价",
    )

    assert order.subtotal == Decimal("250.00")
    assert order.total_price == Decimal("250.00")
    assert order.deposit_amount == Decimal("2000.00")
    assert order.items[0].subtotal == Decimal("250.00")
    change = db.query(OrderChange).filter_by(order_id=order.id, change_type="rent").one()
    assert change.reason == "线下议价"


def test_staff_cannot_raise_rent_above_paid_amount(db, seeded):
    order = _create_order(db, seeded)
    order = order_service.confirm_payment(
        db, order, Decimal("270"), "ok", seeded["staff"].id
    )

    with pytest.raises(OrderError) as exc:
        order_service.update_order_rent(
            db,
            order,
            rent_amount=Decimal("300"),
            operator_id=seeded["staff"].id,
            version=order.version,
        )

    assert exc.value.code == "underpaid"


def test_review_approve_can_update_final_rent(db, seeded):
    order = _create_order(db, seeded)

    order = order_service.review_order(
        db,
        order,
        approve=True,
        operator_id=seeded["staff"].id,
        rent_amount=Decimal("250"),
        paid_amount=Decimal("250"),
        payment_note="线下收款",
    )

    assert order.status == "confirmed"
    assert order.subtotal == Decimal("250.00")
    assert order.total_price == Decimal("250.00")
    assert order.paid_amount == Decimal("250.00")
    assert order.deposit_amount == Decimal("2000.00")


def test_review_approve_rejects_underpaid_final_rent(db, seeded):
    order = _create_order(db, seeded)

    with pytest.raises(OrderError) as exc:
        order_service.review_order(
            db,
            order,
            approve=True,
            operator_id=seeded["staff"].id,
            rent_amount=Decimal("250"),
            paid_amount=Decimal("249.99"),
        )

    assert exc.value.code == "underpaid"


def test_cancel_releases_inventory(db, seeded):
    """取消后库存应回归。"""
    from app.services import inventory_service
    order = _create_order(db, seeded, qty=3)
    a = inventory_service.get_config_availability(db, seeded["config"], date(2024, 9, 1), date(2024, 9, 3))
    assert a.min_available_in_range == 0
    order_service.cancel_order(db, order, operator_id=seeded["user"].id)
    a2 = inventory_service.get_config_availability(db, seeded["config"], date(2024, 9, 1), date(2024, 9, 3))
    assert a2.min_available_in_range == 3


def test_auto_cancel_unpaid_order_after_one_hour(db, seeded):
    """客户超过 1 小时未付款: 自动取消并释放库存。"""
    from app.services import inventory_service

    now = datetime(2024, 9, 1, 12, 0, 0)
    order = _create_order(db, seeded, qty=3)
    order.created_at = now - timedelta(hours=1, minutes=1)
    order.updated_at = order.created_at
    db.commit()

    stats = order_service.auto_cancel_stale_orders(db, now=now)
    db.refresh(order)

    assert stats == {"customer_unpaid": 1, "merchant_unprocessed": 0, "total": 1}
    assert order.status == "cancelled"
    a = inventory_service.get_config_availability(
        db, seeded["config"], date(2024, 9, 1), date(2024, 9, 3)
    )
    assert a.min_available_in_range == 3
    change = db.query(OrderChange).filter_by(order_id=order.id, change_type="auto_cancel").one()
    assert "客户超过 1 小时未付款" in change.reason


def test_auto_cancel_keeps_recent_unpaid_order(db, seeded):
    now = datetime(2024, 9, 1, 12, 0, 0)
    order = _create_order(db, seeded)
    order.created_at = now - timedelta(minutes=59)
    order.updated_at = order.created_at
    db.commit()

    stats = order_service.auto_cancel_stale_orders(db, now=now)
    db.refresh(order)

    assert stats == {"customer_unpaid": 0, "merchant_unprocessed": 0, "total": 0}
    assert order.status == "pending_payment"


def test_auto_cancel_default_clock_keeps_just_created_database_timestamp(db, seeded):
    """数据库 UTC 时间戳与默认扫描时钟必须使用同一基准。"""
    order = _create_order(db, seeded)

    stats = order_service.auto_cancel_stale_orders(db)
    db.refresh(order)

    assert stats == {"customer_unpaid": 0, "merchant_unprocessed": 0, "total": 0}
    assert order.status == "pending_payment"


def test_auto_cancel_paid_unprocessed_after_twelve_hours(db, seeded):
    """已收款但商家超过 12 小时未确认档期: 自动取消, 不收手续费。"""
    from app.services import inventory_service

    now = datetime(2024, 9, 1, 12, 0, 0)
    order = _create_order(db, seeded, qty=3)
    order = order_service.confirm_payment(
        db, order, Decimal("810"), "客户已转账", seeded["staff"].id
    )
    order.updated_at = now - timedelta(hours=12, minutes=1)
    db.commit()

    stats = order_service.auto_cancel_stale_orders(db, now=now)
    db.refresh(order)

    assert stats == {"customer_unpaid": 0, "merchant_unprocessed": 1, "total": 1}
    assert order.status == "cancelled"
    a = inventory_service.get_config_availability(
        db, seeded["config"], date(2024, 9, 1), date(2024, 9, 3)
    )
    assert a.min_available_in_range == 3
    change = db.query(OrderChange).filter_by(order_id=order.id, change_type="auto_cancel").one()
    assert change.new_value["cancellation_fee"] == "0.00"
    assert change.new_value["refund_amount"] == "810.00"
    assert "商家超过 12 小时未处理" in change.reason


def test_auto_cancel_keeps_recent_paid_unprocessed_order(db, seeded):
    now = datetime(2024, 9, 1, 12, 0, 0)
    order = _create_order(db, seeded)
    order = order_service.confirm_payment(
        db, order, Decimal("270"), "客户已转账", seeded["staff"].id
    )
    order.updated_at = now - timedelta(hours=11, minutes=59)
    db.commit()

    stats = order_service.auto_cancel_stale_orders(db, now=now)
    db.refresh(order)

    assert stats == {"customer_unpaid": 0, "merchant_unprocessed": 0, "total": 0}
    assert order.status == "paid"


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


def test_reservation_to_order_rejects_other_user(db, seeded):
    other = User(phone="13800000009", name="其他客户", role="customer")
    db.add(other)
    db.commit()
    r = reservation_service.create_reservation(
        db, seeded["config"], 1, date(2024, 9, 1), date(2024, 9, 3), user_id=other.id
    )
    db.commit()

    with pytest.raises(OrderError) as exc:
        order_service.create_order(
            db,
            user_id=seeded["user"].id,
            items=[{"camera_config_id": seeded["config"].id, "quantity": 1}],
            rental_start=date(2024, 9, 1),
            rental_end=date(2024, 9, 3),
            reservation_id=r.id,
        )

    assert exc.value.code == "reservation_forbidden"


def test_reservation_to_order_rejects_expired_reservation(db, seeded):
    r = reservation_service.create_reservation(
        db, seeded["config"], 1, date(2024, 9, 1), date(2024, 9, 3), user_id=seeded["user"].id
    )
    r.expires_at = datetime.now() - timedelta(minutes=1)
    db.commit()

    with pytest.raises(OrderError) as exc:
        order_service.create_order(
            db,
            user_id=seeded["user"].id,
            items=[{"camera_config_id": seeded["config"].id, "quantity": 1}],
            rental_start=date(2024, 9, 1),
            rental_end=date(2024, 9, 3),
            reservation_id=r.id,
        )

    assert exc.value.code == "reservation_expired"


def test_reservation_to_order_requires_matching_content(db, seeded):
    r = reservation_service.create_reservation(
        db, seeded["config"], 1, date(2024, 9, 1), date(2024, 9, 3), user_id=seeded["user"].id
    )
    db.commit()

    with pytest.raises(OrderError) as exc:
        order_service.create_order(
            db,
            user_id=seeded["user"].id,
            items=[{"camera_config_id": seeded["config"].id, "quantity": 1}],
            rental_start=date(2024, 9, 1),
            rental_end=date(2024, 9, 4),
            reservation_id=r.id,
        )

    assert exc.value.code == "reservation_mismatch"
