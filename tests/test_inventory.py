"""按日期库存测试 (Spec §9.1 — 最关键、最易错的逻辑)。"""
from __future__ import annotations

from datetime import date

from app.services import inventory_service, reservation_service


def test_availability_empty(db, seeded):
    cfg = seeded["config"]
    avail = inventory_service.get_config_availability(
        db, cfg, date(2024, 9, 1), date(2024, 9, 3)
    )
    assert avail.min_available_in_range == 3
    assert len(avail.daily_breakdown) == 3  # 含起含止 3 天


def test_rented_range_does_not_block_other_dates(db, seeded):
    """🔴 9/1-3 租出 1 台后, 9/5 仍应满额可用。"""
    cfg = seeded["config"]
    reservation_service.create_reservation(
        db, cfg, quantity=1, start=date(2024, 9, 1), end=date(2024, 9, 3)
    )
    db.commit()

    # 9/1-3 区间应少 1 台
    a1 = inventory_service.get_config_availability(db, cfg, date(2024, 9, 1), date(2024, 9, 3))
    assert a1.min_available_in_range == 2

    # 9/5 不受影响
    a2 = inventory_service.get_config_availability(db, cfg, date(2024, 9, 5), date(2024, 9, 5))
    assert a2.min_available_in_range == 3


def test_min_available_across_overlapping_occupancy(db, seeded):
    """跨天占用应正确登记每一天, 区间最小值才是答案。"""
    cfg = seeded["config"]
    # 9/1-2 占 2 台, 9/2-3 再占 1 台 => 9/2 占用最多(3台), 当天可用=0
    reservation_service.create_reservation(db, cfg, 2, date(2024, 9, 1), date(2024, 9, 2))
    reservation_service.create_reservation(db, cfg, 1, date(2024, 9, 2), date(2024, 9, 3))
    db.commit()

    avail = inventory_service.get_config_availability(db, cfg, date(2024, 9, 1), date(2024, 9, 3))
    by_day = {d.day.isoformat(): d.available for d in avail.daily_breakdown}
    assert by_day["2024-09-01"] == 1  # 占2
    assert by_day["2024-09-02"] == 0  # 占3
    assert by_day["2024-09-03"] == 2  # 占1
    assert avail.min_available_in_range == 0


def test_insufficient_inventory_raises(db, seeded):
    cfg = seeded["config"]
    with __import__("pytest").raises(reservation_service.InventoryError):
        reservation_service.create_reservation(db, cfg, 4, date(2024, 9, 1), date(2024, 9, 3))
