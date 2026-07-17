"""租前、租中、租后陪伴事件与安全边界测试。"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import CompanionEvent, Order, OrderItem
from app.services import companion_service


def _order(db, seeded, *, status: str, start: date, end: date, order_id: str) -> Order:
    order = Order(
        id=order_id,
        user_id=seeded["user"].id,
        status=status,
        subtotal=Decimal("270"),
        deposit_amount=Decimal("2000"),
        total_price=Decimal("270"),
        rental_start=start,
        rental_end=end,
        carrier="顺丰速运",
        tracking_no="SF123456",
    )
    order.items.append(
        OrderItem(
            camera_config_id=seeded["config"].id,
            quantity=1,
            price_per_day=Decimal("90"),
            discount_rate=Decimal("1"),
            subtotal=Decimal("270"),
        )
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def test_shipped_companion_has_guides_and_honest_logistics(db, seeded):
    today = date.today()
    order = _order(
        db,
        seeded,
        status="shipped",
        start=today + timedelta(days=2),
        end=today + timedelta(days=5),
        order_id="ORD-COMP-1",
    )

    result = companion_service.build_companion(db, order, today=today)

    assert result["phase"] == "in_transit"
    assert result["logistics"]["source"] == "manual"
    assert result["logistics"]["current_location"] is None
    assert result["logistics"]["estimated_delivery"] is None
    assert "待物流服务接入" in result["logistics"]["notice"]
    assert result["device_guides"][0]["camera_id"] == "R5"
    assert len(result["events"]) == 2

    # 重复刷新不能重复创建推送。
    companion_service.build_companion(db, order, today=today)
    count = db.execute(
        select(CompanionEvent).where(CompanionEvent.order_id == order.id)
    ).scalars().all()
    assert len(count) == 2


def test_return_reminder_is_idempotent(db, seeded):
    today = date.today()
    order = _order(
        db,
        seeded,
        status="active",
        start=today - timedelta(days=2),
        end=today + timedelta(days=1),
        order_id="ORD-COMP-2",
    )

    assert companion_service.ensure_events(db, order, today=today) == 2
    assert companion_service.ensure_events(db, order, today=today) == 0
    result = companion_service.build_companion(db, order, today=today)
    assert result["phase"] == "in_use"
    assert any(e["event_type"] == "return_reminder" for e in result["events"])
    assert "腾讯地图搜索入口" in result["return_guide"]["outlet_notice"]


def test_feedback_and_opt_in_showcase_only_after_completion(db, seeded):
    today = date.today()
    order = _order(
        db,
        seeded,
        status="active",
        start=today - timedelta(days=3),
        end=today,
        order_id="ORD-COMP-3",
    )
    with pytest.raises(ValueError, match="订单完成后"):
        companion_service.submit_feedback(db, order, 5, "很好用", None, False)

    order.status = "completed"
    db.commit()
    feedback = companion_service.submit_feedback(
        db,
        order,
        5,
        "很好用",
        "https://example.com/work.jpg",
        True,
    )
    assert feedback.showcase_allowed is True
    items = companion_service.showcase(db)
    assert len(items) == 1
    assert items[0]["camera_name"] == seeded["config"].config_name
    assert items[0]["share_url"] == "https://example.com/work.jpg"


def test_phase_derivation_covers_order_lifecycle(db, seeded):
    today = date.today()
    order = _order(
        db,
        seeded,
        status="confirmed",
        start=today + timedelta(days=2),
        end=today + timedelta(days=5),
        order_id="ORD-COMP-4",
    )
    assert companion_service.derive_phase(order, today) == "pre_rental"
    order.status = "shipped"
    assert companion_service.derive_phase(order, today) == "in_transit"
    order.status = "active"
    assert companion_service.derive_phase(order, today) == "in_use"
    order.status = "returned"
    assert companion_service.derive_phase(order, today) == "return_due"
    order.status = "completed"
    assert companion_service.derive_phase(order, today) == "post_rental"
