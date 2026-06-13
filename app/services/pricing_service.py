"""价格计算服务 —— 档位计价模型 (取代原日租×折扣模型)。

计价规则 (业务方提供的价格表):
  1-2 天  -> two_day_price (两天租金)
  3 天    -> three_day_price (三天租金)
  >3 天   -> three_day_price + (天数 - 3) × extra_day_price (三天以上续租/天)
天数 = 含起含止，9/1–9/3 = 3 天。
总应付 = 租金 + 押金。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def rental_days(start: date, end: date) -> int:
    """租赁天数: 含起含止。9/1–9/3 = 3 天。"""
    return (end - start).days + 1


@dataclass
class PriceBreakdown:
    days: int
    two_day_price: Decimal
    three_day_price: Decimal
    extra_day_price: Decimal
    extra_days: int          # 超过 3 天的天数
    basis: str               # 计价档位说明
    rent: Decimal            # 租金合计(单件)
    deposit: Decimal
    total_due: Decimal       # 租金 + 押金(单件)

    # —— 兼容旧调用方的别名 ——
    @property
    def final_price(self) -> Decimal:
        return self.rent

    @property
    def subtotal(self) -> Decimal:
        return self.rent


def calculate_price(
    two_day_price: Decimal,
    three_day_price: Decimal,
    extra_day_price: Decimal,
    deposit: Decimal,
    start: date,
    end: date,
) -> PriceBreakdown:
    """按档位计算单件租赁价格。"""
    days = rental_days(start, end)
    if days < 1:
        raise ValueError("租期至少 1 天")

    two = Decimal(two_day_price)
    three = Decimal(three_day_price)
    extra = Decimal(extra_day_price)
    deposit = Decimal(deposit)

    extra_days = 0
    if days <= 2:
        rent = two
        basis = "两天档"
    elif days == 3:
        rent = three
        basis = "三天档"
    else:
        extra_days = days - 3
        rent = three + extra * extra_days
        basis = f"三天档 + 续租 {extra_days} 天"

    rent = _money(rent)
    deposit = _money(deposit)
    return PriceBreakdown(
        days=days,
        two_day_price=_money(two),
        three_day_price=_money(three),
        extra_day_price=_money(extra),
        extra_days=extra_days,
        basis=basis,
        rent=rent,
        deposit=deposit,
        total_due=_money(rent + deposit),
    )
