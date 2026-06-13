"""价格计算测试 —— 档位计价模型(两天/三天/续租)。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services import pricing_service


def _p(two, three, extra, dep, s, e):
    return pricing_service.calculate_price(
        Decimal(str(two)), Decimal(str(three)), Decimal(str(extra)),
        Decimal(str(dep)), s, e,
    )


def test_rental_days_inclusive():
    assert pricing_service.rental_days(date(2024, 9, 1), date(2024, 9, 3)) == 3


def test_one_and_two_days_use_two_day_price():
    # 1 天和 2 天都按"两天租金"
    p1 = _p(100, 120, 25, 0, date(2024, 9, 1), date(2024, 9, 1))
    assert p1.days == 1 and p1.rent == Decimal("100.00") and p1.basis == "两天档"
    p2 = _p(100, 120, 25, 0, date(2024, 9, 1), date(2024, 9, 2))
    assert p2.days == 2 and p2.rent == Decimal("100.00")


def test_three_days_use_three_day_price():
    p = _p(100, 120, 25, 0, date(2024, 9, 1), date(2024, 9, 3))
    assert p.days == 3 and p.rent == Decimal("120.00") and p.basis == "三天档"


def test_over_three_days_adds_extra():
    # 5 天 = 三天价 120 + (5-3)×25 = 170
    p = _p(100, 120, 25, 0, date(2024, 9, 1), date(2024, 9, 5))
    assert p.days == 5 and p.extra_days == 2 and p.rent == Decimal("170.00")


def test_total_due_adds_deposit():
    p = _p(100, 120, 25, 2000, date(2024, 9, 1), date(2024, 9, 3))
    assert p.total_due == Decimal("2120.00")


def test_real_catalog_example_g12_7days():
    # 佳能G12: 两天100/三天120/续租25; 租7天 = 120 + 4×25 = 220
    p = _p(100, 120, 25, 0, date(2024, 9, 1), date(2024, 9, 7))
    assert p.days == 7 and p.rent == Decimal("220.00")
