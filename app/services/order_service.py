"""订单服务 —— 订单全流程 (Spec 3.1 状态机 / 4.5 API / PRD 3.6 取消规则)。

要点:
- 人工确认收款 (pending_payment -> paid), 无任何自动支付逻辑。
- 乐观锁 version 防并发覆盖。
- 所有变更写 order_changes 审计。
- 创建订单时把预留占用转为订单占用, 或直接登记订单占用。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.camera import CameraConfig
from app.models.inventory import Occupancy
from app.models.order import Order, OrderChange, OrderItem
from app.models.reservation import Reservation
from app.services import inventory_service, pricing_service
from app.services.reservation_service import InventoryError

_CENT = Decimal("0.01")


def _money(v: Decimal) -> Decimal:
    return Decimal(v).quantize(_CENT, rounding=ROUND_HALF_UP)


def _sync_to_feishu(db: Session, order: Order) -> None:
    """订单变更后同步到飞书 (Phase 2)。关闭时静默跳过。"""
    if not settings.feishu_enabled:
        return
    from app.integrations import feishu

    ok = feishu.push_order(order)
    order.sync_status = "synced" if ok else "sync_pending"
    db.commit()


# ============ 状态机 ============
# 状态 -> 允许转入的状态集合 (Spec 3.1)
# 🆕 v2.1: shipped 可直接 -> completed(商家验收), 跳过 active/returned;
#          active/returned 仍保留以兼容旧数据。
ALLOWED_TRANSITIONS = {
    "draft": {"pending_payment", "cancelled"},
    "pending_payment": {"paid", "cancelled"},
    "paid": {"confirmed", "cancelled"},
    "confirmed": {"shipped", "cancelled"},
    "shipped": {"completed", "active"},
    "active": {"returned", "completed"},
    "returned": {"completed"},
    "completed": set(),
    "cancelled": set(),
}

# 🆕 v2.1: 内部状态 -> 客户/商家可见中文标签 (Spec 3.1.1, 单一事实来源)
DISPLAY_STATUS = {
    "draft": "草稿",
    "pending_payment": "商家审核中",
    "paid": "商家审核中",
    "confirmed": "已确认档期（待发货）",
    "shipped": "已发货",
    "active": "使用中",
    "returned": "待验收",
    "completed": "订单已完结",
    "cancelled": "已取消",
}


def display_status(order: Order) -> str:
    """订单的客户/商家可见中文标签。审核驳回时附原因。"""
    label = DISPLAY_STATUS.get(order.status, order.status)
    if order.status == "pending_payment" and order.review_note:
        return f"{label}（审核未通过：{order.review_note}）"
    return label


class OrderError(Exception):
    def __init__(self, message: str, code: str = "order_error"):
        super().__init__(message)
        self.message = message
        self.code = code


class ConflictError(OrderError):
    """乐观锁版本冲突。"""

    def __init__(self, message: str = "订单已被他人修改，请刷新后重试"):
        super().__init__(message, code="version_conflict")


def generate_order_id(db: Session) -> str:
    """生成订单号 ORD + YYYYMMDD + 3 位日内序号。"""
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"ORD{today}"
    count = db.execute(
        select(func.count()).select_from(Order).where(Order.id.like(f"{prefix}%"))
    ).scalar_one()
    return f"{prefix}{count + 1:03d}"


def _audit(
    db: Session,
    order_id: str,
    change_type: str,
    changed_by: Optional[str],
    old_value: Optional[dict] = None,
    new_value: Optional[dict] = None,
    reason: Optional[str] = None,
) -> None:
    db.add(
        OrderChange(
            order_id=order_id,
            change_type=change_type,
            changed_by=changed_by,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
        )
    )


def create_order(
    db: Session,
    user_id: str,
    items: List[dict],
    rental_start: date,
    rental_end: date,
    delivery_address_id: Optional[str] = None,
    reservation_id: Optional[str] = None,
    created_by: Optional[str] = None,
    source: str = "ai",
) -> Order:
    """创建订单。

    items: [{"camera_config_id": str, "quantity": int}, ...]
    若带 reservation_id, 复用该预留的占用(转为订单占用); 否则现场校验库存并登记占用。
    """
    if rental_end < rental_start:
        raise OrderError("租期结束日不能早于开始日", code="invalid_period")

    reservation: Optional[Reservation] = None
    if reservation_id:
        reservation = db.get(Reservation, reservation_id)
        if not reservation or reservation.status != "active":
            raise OrderError("预留不存在或已失效", code="reservation_invalid")

    order_id = generate_order_id(db)
    order = Order(
        id=order_id,
        user_id=user_id,
        status="pending_payment",
        rental_start=rental_start,
        rental_end=rental_end,
        delivery_address_id=delivery_address_id,
        created_by=created_by or user_id,
        last_modified_by=created_by or user_id,
        source=source,
        version=1,
    )

    subtotal_sum = Decimal("0")
    deposit_sum = Decimal("0")

    for item in items:
        config = db.get(CameraConfig, item["camera_config_id"])
        if not config:
            raise OrderError(
                f"配置不存在: {item['camera_config_id']}", code="config_not_found"
            )
        qty = int(item.get("quantity", 1))

        # 校验库存(若复用预留, 排除预留自身占用避免重复计数)
        if not inventory_service.is_available(
            db, config, rental_start, rental_end, qty,
            exclude_ref_id=reservation_id,
        ):
            avail = inventory_service.get_config_availability(
                db, config, rental_start, rental_end, exclude_ref_id=reservation_id
            )
            raise InventoryError(
                f"库存不足: {config.config_name} 区间最多可租 "
                f"{avail.min_available_in_range} 台",
                details={
                    "config_id": config.id,
                    "requested": qty,
                    "min_available": avail.min_available_in_range,
                    "shortage_days": [
                        {"date": d.day.isoformat(), "available": d.available}
                        for d in avail.daily_breakdown
                        if d.available < qty
                    ],
                },
            )

        price = pricing_service.calculate_price(
            config.two_day_price, config.three_day_price, config.extra_day_price,
            config.deposit_amount, rental_start, rental_end,
        )
        line_rent = _money(price.rent * qty)
        line_deposit = _money(config.deposit_amount * qty)
        # 档位计价无折扣概念: 小计=租金, 折扣=0
        per_day = _money(price.rent / price.days) if price.days else Decimal("0")

        order.items.append(
            OrderItem(
                camera_config_id=config.id,
                quantity=qty,
                price_per_day=per_day,
                discount_rate=Decimal("1"),
                subtotal=line_rent,
            )
        )
        subtotal_sum += line_rent
        deposit_sum += line_deposit

        # 登记订单占用(每台一条)
        for _ in range(qty):
            db.add(
                Occupancy(
                    config_id=config.id,
                    occupancy_type="order",
                    start_date=rental_start,
                    end_date=rental_end,
                    ref_id=order_id,
                    status="active",
                )
            )

    order.subtotal = _money(subtotal_sum)
    order.deposit_amount = _money(deposit_sum)
    order.discount_amount = Decimal("0.00")
    order.total_price = _money(subtotal_sum)

    db.add(order)
    db.flush()

    # 预留转单: 释放预留占用(订单占用已新建), 标记预留 confirmed
    if reservation:
        reservation.status = "confirmed"
        reservation.order_id = order_id
        res_occs = db.execute(
            select(Occupancy).where(
                Occupancy.ref_id == reservation.id,
                Occupancy.occupancy_type == "reservation",
                Occupancy.status == "active",
            )
        ).scalars().all()
        for occ in res_occs:
            occ.status = "released"

    _audit(
        db, order_id, "create", created_by or user_id,
        new_value={"status": "pending_payment", "total_price": str(order.total_price)},
    )
    db.commit()
    db.refresh(order)
    _sync_to_feishu(db, order)
    return order


def _transition(order: Order, target: str) -> None:
    allowed = ALLOWED_TRANSITIONS.get(order.status, set())
    if target not in allowed:
        raise OrderError(
            f"非法状态转换: {order.status} -> {target}",
            code="invalid_transition",
        )
    order.status = target


def _check_version(order: Order, version: Optional[int]) -> None:
    if version is not None and order.version != version:
        raise ConflictError()


def confirm_payment(
    db: Session,
    order: Order,
    paid_amount: Decimal,
    payment_note: Optional[str],
    operator_id: Optional[str],
    version: Optional[int] = None,
) -> Order:
    """🔴 人工确认收款: pending_payment -> paid。无自动支付逻辑。"""
    _check_version(order, version)
    old = {"status": order.status, "paid_amount": str(order.paid_amount)}
    _transition(order, "paid")
    order.paid_amount = _money(paid_amount)
    order.payment_note = payment_note
    order.version += 1
    order.last_modified_by = operator_id
    _audit(
        db, order.id, "payment", operator_id, old_value=old,
        new_value={"status": "paid", "paid_amount": str(order.paid_amount)},
        reason=payment_note,
    )
    db.commit()
    db.refresh(order)
    _sync_to_feishu(db, order)
    return order


def advance_status(
    db: Session,
    order: Order,
    target: str,
    operator_id: Optional[str],
    version: Optional[int] = None,
) -> Order:
    """推进订单状态(审核/发货/签收/归还/完成)。"""
    _check_version(order, version)
    old = {"status": order.status}
    _transition(order, target)
    order.version += 1
    order.last_modified_by = operator_id
    _audit(
        db, order.id, "status", operator_id,
        old_value=old, new_value={"status": target},
    )
    db.commit()
    db.refresh(order)
    _sync_to_feishu(db, order)
    return order


# ============ v2.1 商家审核 / 物流 / 验收 ============
def review_order(
    db: Session,
    order: Order,
    approve: bool,
    operator_id: Optional[str],
    paid_amount: Optional[Decimal] = None,
    payment_note: Optional[str] = None,
    review_note: Optional[str] = None,
    version: Optional[int] = None,
) -> Order:
    """🆕 商家审核(Spec 4.8)。

    approve=True: 一步完成「确认收款 + 放行档期」(pending_payment->paid->confirmed),
                  记录 paid_amount/payment_note, 清空 review_note。
    approve=False: 状态留在 pending_payment, 写 review_note(驳回原因)。
    """
    _check_version(order, version)
    if order.status != "pending_payment":
        raise OrderError(
            f"当前状态 {order.status} 不可审核(仅商家审核中可审)",
            code="invalid_transition",
        )
    old = {"status": order.status, "paid_amount": str(order.paid_amount)}

    if not approve:
        order.review_note = review_note
        order.version += 1
        order.last_modified_by = operator_id
        _audit(
            db, order.id, "review", operator_id, old_value=old,
            new_value={"status": order.status, "approved": False},
            reason=review_note,
        )
        db.commit()
        db.refresh(order)
        _sync_to_feishu(db, order)
        return order

    # 审核通过: pending_payment -> paid -> confirmed
    _transition(order, "paid")
    if paid_amount is not None:
        order.paid_amount = _money(paid_amount)
    order.payment_note = payment_note
    _transition(order, "confirmed")
    order.review_note = None
    order.version += 1
    order.last_modified_by = operator_id
    _audit(
        db, order.id, "review", operator_id, old_value=old,
        new_value={"status": "confirmed", "approved": True,
                   "paid_amount": str(order.paid_amount)},
        reason=payment_note,
    )
    db.commit()
    db.refresh(order)
    _sync_to_feishu(db, order)
    return order


def ship_order(
    db: Session,
    order: Order,
    carrier: str,
    tracking_no: str,
    operator_id: Optional[str],
    version: Optional[int] = None,
) -> Order:
    """🆕 上传物流并发货(Spec 4.8): confirmed -> shipped, 写 carrier/tracking_no。"""
    _check_version(order, version)
    if not (carrier and carrier.strip()) or not (tracking_no and tracking_no.strip()):
        raise OrderError("快递公司与物流单号均不能为空", code="missing_logistics")
    old = {"status": order.status}
    _transition(order, "shipped")
    order.carrier = carrier.strip()
    order.tracking_no = tracking_no.strip()
    order.version += 1
    order.last_modified_by = operator_id
    _audit(
        db, order.id, "status", operator_id, old_value=old,
        new_value={"status": "shipped", "carrier": order.carrier,
                   "tracking_no": order.tracking_no},
    )
    db.commit()
    db.refresh(order)
    _sync_to_feishu(db, order)
    return order


def accept_order(
    db: Session,
    order: Order,
    operator_id: Optional[str],
    version: Optional[int] = None,
) -> Order:
    """🆕 商家验收完结(Spec 4.8): shipped -> completed(默认), 跳过 active/returned。"""
    _check_version(order, version)
    old = {"status": order.status}
    _transition(order, "completed")
    order.version += 1
    order.last_modified_by = operator_id
    _audit(
        db, order.id, "status", operator_id, old_value=old,
        new_value={"status": "completed"},
    )
    db.commit()
    db.refresh(order)
    _sync_to_feishu(db, order)
    return order


def _release_order_occupancy(db: Session, order_id: str) -> None:
    occs = db.execute(
        select(Occupancy).where(
            Occupancy.ref_id == order_id,
            Occupancy.occupancy_type == "order",
            Occupancy.status == "active",
        )
    ).scalars().all()
    for occ in occs:
        occ.status = "released"


def cancel_order(
    db: Session,
    order: Order,
    operator_id: Optional[str],
    version: Optional[int] = None,
    reason: Optional[str] = None,
) -> dict:
    """取消订单 (PRD 3.6)。返回退款与手续费明细。

    - pending_payment 且下单 48h 内: 免费, 释放占用
    - paid / confirmed: 扣 10% 手续费, 退余额
    - shipped 及之后: 不可直接取消
    """
    _check_version(order, version)
    if order.status not in ALLOWED_TRANSITIONS or "cancelled" not in ALLOWED_TRANSITIONS[order.status]:
        raise OrderError(
            f"当前状态 {order.status} 不可取消(已发货需走拒收/人工)",
            code="cannot_cancel",
        )

    cancellation_fee = Decimal("0.00")
    if order.status in ("paid", "confirmed"):
        cancellation_fee = _money(order.total_price * Decimal(str(settings.cancellation_fee_rate)))
    refund_amount = _money(order.paid_amount - cancellation_fee)
    if refund_amount < 0:
        refund_amount = Decimal("0.00")

    old = {"status": order.status}
    order.status = "cancelled"
    order.version += 1
    order.last_modified_by = operator_id
    _release_order_occupancy(db, order.id)
    _audit(
        db, order.id, "cancel", operator_id, old_value=old,
        new_value={
            "status": "cancelled",
            "cancellation_fee": str(cancellation_fee),
            "refund_amount": str(refund_amount),
        },
        reason=reason,
    )
    db.commit()
    db.refresh(order)
    return {
        "order_id": order.id,
        "status": "cancelled",
        "cancellation_fee": cancellation_fee,
        "refund_amount": refund_amount,
    }


def extend_order(
    db: Session,
    order: Order,
    new_end_date: date,
    operator_id: Optional[str],
    version: Optional[int] = None,
) -> dict:
    """延长租期 (改单)。校验新增区间库存, 重算价格, 更新占用。"""
    _check_version(order, version)
    if order.status not in ("pending_payment", "paid", "confirmed"):
        raise OrderError(
            f"当前状态 {order.status} 不支持改期", code="cannot_modify"
        )
    if new_end_date <= order.rental_end:
        raise OrderError("新结束日必须晚于当前结束日", code="invalid_period")

    old_end = order.rental_end
    old_total = order.total_price

    # 校验整段新区间库存(排除本订单已有占用)
    new_subtotal = Decimal("0")
    for item in order.items:
        config = db.get(CameraConfig, item.camera_config_id)
        if not inventory_service.is_available(
            db, config, order.rental_start, new_end_date, item.quantity,
            exclude_ref_id=order.id,
        ):
            raise InventoryError(
                f"延期失败: {config.config_name} 在新区间库存不足",
                details={"config_id": config.id},
            )
        price = pricing_service.calculate_price(
            config.two_day_price, config.three_day_price, config.extra_day_price,
            config.deposit_amount, order.rental_start, new_end_date,
        )
        per_day = _money(price.rent / price.days) if price.days else Decimal("0")
        item.price_per_day = per_day
        item.discount_rate = Decimal("1")
        item.subtotal = _money(price.rent * item.quantity)
        new_subtotal += item.subtotal

    # 更新订单占用的结束日
    occs = db.execute(
        select(Occupancy).where(
            Occupancy.ref_id == order.id,
            Occupancy.occupancy_type == "order",
            Occupancy.status == "active",
        )
    ).scalars().all()
    for occ in occs:
        occ.end_date = new_end_date

    order.rental_end = new_end_date
    order.subtotal = _money(new_subtotal)
    order.discount_amount = Decimal("0.00")
    order.total_price = _money(new_subtotal)
    order.version += 1
    order.last_modified_by = operator_id
    price_diff = _money(order.total_price - old_total)

    _audit(
        db, order.id, "update", operator_id,
        old_value={"rental_end": old_end.isoformat(), "total_price": str(old_total)},
        new_value={"rental_end": new_end_date.isoformat(), "total_price": str(order.total_price)},
        reason="extend",
    )
    db.commit()
    db.refresh(order)
    return {
        "order_id": order.id,
        "new_end_date": new_end_date,
        "price_diff": price_diff,
        "total_price": order.total_price,
        "version": order.version,
    }
