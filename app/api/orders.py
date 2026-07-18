"""订单 API (Spec 4.5) + 预留 API。

需认证 (租客 HttpOnly Cookie 会话)。C 端只能操作自己的订单; B 端 staff/admin 可操作全部。
状态推进/确认收款等 B 端操作需 staff 权限。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_staff_user
from app.database import get_db
from app.models.camera import CameraConfig
from app.models.order import Order
from app.models.user import User, UserAddress
from app.schemas.order import (
    AcceptRequest,
    CancelResponse,
    OrderCreateRequest,
    OrderCreateResponse,
    OrderExtendRequest,
    OrderItemOut,
    OrderOut,
    PaymentConfirmRequest,
    RentUpdateRequest,
    ReviewRequest,
    ShipRequest,
    ShippingAddressOut,
    StatusAdvanceRequest,
)
from app.services import order_service
from app.services.order_service import ConflictError, OrderError
from app.services.reservation_service import InventoryError

router = APIRouter(prefix="/api", tags=["orders"])


def _shipping_address_out(address: Optional[UserAddress]) -> Optional[ShippingAddressOut]:
    if not address:
        return None
    province = address.province or ""
    city = address.city or ""
    district = address.district or ""
    detail = address.detail_address or ""
    return ShippingAddressOut(
        receiver_name=address.receiver_name or "",
        phone=address.phone or "",
        province=province,
        city=city,
        district=district,
        detail_address=detail,
        full_address=f"{province}{city}{district}{detail}",
    )


def _order_out(db: Session, order: Order) -> OrderOut:
    shipping_address = _shipping_address_out(
        db.get(UserAddress, order.delivery_address_id)
        if order.delivery_address_id else None
    )
    return OrderOut(
        order_id=order.id,
        status=order.status,
        display_status=order_service.display_status(order),
        subtotal=order.subtotal,
        deposit=order.deposit_amount,
        discount_amount=order.discount_amount,
        total_price=order.total_price,
        paid_amount=order.paid_amount,
        rental_start=order.rental_start,
        rental_end=order.rental_end,
        version=order.version,
        carrier=order.carrier,
        tracking_no=order.tracking_no,
        review_note=order.review_note,
        shipping_address=shipping_address,
        user_id=order.user_id,
        items=[
            OrderItemOut(
                camera_config_id=i.camera_config_id,
                quantity=i.quantity,
                price_per_day=i.price_per_day,
                discount_rate=i.discount_rate,
                subtotal=i.subtotal,
            )
            for i in order.items
        ],
    )


def _get_owned_order(db: Session, order_id: str, user: User) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, detail={"error": "订单不存在", "error_code": "not_found"})
    # 租客端只能操作本人订单; 员工操作走后台接口。
    if order.user_id != user.id:
        raise HTTPException(403, detail={"error": "无权访问该订单", "error_code": "forbidden"})
    return order


@router.post("/orders", response_model=OrderCreateResponse, status_code=201)
def create_order(
    body: OrderCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    shipping = body.shipping_address
    address = UserAddress(
        user_id=user.id,
        address_type="shipping",
        province=shipping.province,
        city=shipping.city,
        district=shipping.district,
        detail_address=shipping.detail_address,
        receiver_name=shipping.receiver_name,
        phone=shipping.phone,
        is_default=False,
    )
    try:
        db.add(address)
        db.flush()
        order = order_service.create_order(
            db,
            user_id=user.id,
            items=[i.model_dump() for i in body.items],
            rental_start=body.rental_start,
            rental_end=body.rental_end,
            delivery_address_id=address.id,
            reservation_id=body.reservation_id,
            created_by=user.id,
        )
    except InventoryError as e:
        db.rollback()
        raise HTTPException(
            422,
            detail={"error": e.message, "error_code": "insufficient_inventory",
                    "details": e.details},
        )
    except OrderError as e:
        db.rollback()
        raise HTTPException(400, detail={"error": e.message, "error_code": e.code})
    except Exception:
        db.rollback()
        raise

    expires = None
    shipping_out = _shipping_address_out(address)
    assert shipping_out is not None
    return OrderCreateResponse(
        order_id=order.id,
        status=order.status,
        total_price=order.total_price,
        deposit=order.deposit_amount,
        shipping_address=shipping_out,
        payment_instruction="请通过线下转账完成支付，并联系客服/财务确认收款。",
        reservation_expires_at=expires,
    )


@router.get("/orders")
def list_orders(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # 该接口只返回本人订单; 员工查看全部走 /orders/admin
    stmt = select(Order).where(
        Order.user_id == user.id,
        Order.customer_deleted_at.is_(None),
    )
    if status:
        stmt = stmt.where(Order.status == status)
    stmt = stmt.order_by(Order.created_at.desc())
    rows = db.execute(stmt.offset((page - 1) * limit).limit(limit)).scalars().all()
    return {"data": [_order_out(db, o) for o in rows], "page": page, "limit": limit}


@router.get("/orders/admin")
def list_orders_admin(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_staff_user),
):
    """🆕 v2.1 商家端订单列表(全部用户)。🆕 v2.2 凭后台登录令牌。"""
    stmt = select(Order)
    if status:
        stmt = stmt.where(Order.status == status)
    stmt = stmt.order_by(Order.created_at.desc())
    rows = db.execute(stmt.offset((page - 1) * limit).limit(limit)).scalars().all()
    return {"data": [_order_out(db, o) for o in rows], "page": page, "limit": limit}


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _order_out(db, _get_owned_order(db, order_id, user))


@router.patch("/orders/{order_id}")
def modify_order(
    order_id: str,
    body: OrderExtendRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = _get_owned_order(db, order_id, user)
    if body.action != "extend":
        raise HTTPException(400, detail={"error": "暂仅支持 extend(延期)", "error_code": "unsupported_action"})
    try:
        result = order_service.extend_order(
            db, order, body.new_end_date, operator_id=user.id, version=body.version
        )
    except ConflictError as e:
        raise HTTPException(409, detail={"error": e.message, "error_code": e.code})
    except InventoryError as e:
        raise HTTPException(422, detail={"error": e.message, "error_code": "insufficient_inventory", "details": e.details})
    except OrderError as e:
        raise HTTPException(400, detail={"error": e.message, "error_code": e.code})
    return {
        "order_id": result["order_id"],
        "new_end_date": result["new_end_date"].isoformat(),
        "price_diff": float(result["price_diff"]),
        "total_price": float(result["total_price"]),
        "version": result["version"],
    }


@router.delete("/orders/{order_id}", response_model=CancelResponse)
def cancel_order(
    order_id: str,
    version: Optional[int] = Query(default=None),
    reason: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = _get_owned_order(db, order_id, user)
    try:
        result = order_service.cancel_order(
            db, order, operator_id=user.id, version=version, reason=reason
        )
    except ConflictError as e:
        raise HTTPException(409, detail={"error": e.message, "error_code": e.code})
    except OrderError as e:
        raise HTTPException(400, detail={"error": e.message, "error_code": e.code})
    return CancelResponse(
        order_id=result["order_id"],
        status=result["status"],
        refund_amount=result["refund_amount"],
        cancellation_fee=result["cancellation_fee"],
    )


@router.delete("/orders/{order_id}/record")
def delete_order_record(
    order_id: str,
    version: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """租客删除终态订单：C 端隐藏，B 端与审计记录保留。"""
    order = _get_owned_order(db, order_id, user)
    try:
        return order_service.delete_order_for_customer(
            db,
            order,
            operator_id=user.id,
            version=version,
        )
    except ConflictError as e:
        raise HTTPException(409, detail={"error": e.message, "error_code": e.code})
    except OrderError as e:
        raise HTTPException(400, detail={"error": e.message, "error_code": e.code})


# ============ B 端操作 ============
@router.post("/orders/{order_id}/confirm-payment", response_model=OrderOut)
def confirm_payment(
    order_id: str,
    body: PaymentConfirmRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_staff_user),
):
    """🔴 人工确认收款。🆕 v2.2 凭后台登录令牌。"""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, detail={"error": "订单不存在", "error_code": "not_found"})
    try:
        order = order_service.confirm_payment(
            db, order, body.paid_amount, body.payment_note,
            operator_id=user.id, version=body.version,
        )
    except ConflictError as e:
        raise HTTPException(409, detail={"error": e.message, "error_code": e.code})
    except OrderError as e:
        raise HTTPException(400, detail={"error": e.message, "error_code": e.code})
    return _order_out(db, order)


@router.post("/orders/{order_id}/advance", response_model=OrderOut)
def advance_status(
    order_id: str,
    body: StatusAdvanceRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_staff_user),
):
    """推进状态(审核/发货/签收/归还/完成)。🆕 v2.2 凭后台登录令牌。"""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, detail={"error": "订单不存在", "error_code": "not_found"})
    try:
        order = order_service.advance_status(
            db, order, body.target, operator_id=user.id, version=body.version
        )
    except ConflictError as e:
        raise HTTPException(409, detail={"error": e.message, "error_code": e.code})
    except OrderError as e:
        raise HTTPException(400, detail={"error": e.message, "error_code": e.code})
    return _order_out(db, order)


def _fetch_order(db: Session, order_id: str) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, detail={"error": "订单不存在", "error_code": "not_found"})
    return order


def _map_order_errors(fn):
    try:
        return fn()
    except ConflictError as e:
        raise HTTPException(409, detail={"error": e.message, "error_code": e.code})
    except OrderError as e:
        code = 422 if e.code in ("invalid_transition", "missing_logistics") else 400
        raise HTTPException(code, detail={"error": e.message, "error_code": e.code})


@router.post("/orders/{order_id}/review", response_model=OrderOut)
def review_order(
    order_id: str,
    body: ReviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_staff_user),
):
    """🆕 v2.1 商家审核(approve 一步放行档期 / reject 留待审核)。🆕 v2.2 凭后台令牌。"""
    order = _fetch_order(db, order_id)
    order = _map_order_errors(lambda: order_service.review_order(
        db, order, approve=body.approve, operator_id=user.id,
        paid_amount=body.paid_amount, rent_amount=body.rent_amount,
        payment_note=body.payment_note,
        review_note=body.review_note, version=body.version,
    ))
    return _order_out(db, order)


@router.post("/orders/{order_id}/rent", response_model=OrderOut)
def update_order_rent(
    order_id: str,
    body: RentUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_staff_user),
):
    """商家修改订单租金。押金只展示，不计入应付。"""
    order = _fetch_order(db, order_id)
    order = _map_order_errors(lambda: order_service.update_order_rent(
        db, order, rent_amount=body.rent_amount,
        operator_id=user.id, version=body.version, reason=body.reason,
    ))
    return _order_out(db, order)


@router.post("/orders/{order_id}/ship", response_model=OrderOut)
def ship_order(
    order_id: str,
    body: ShipRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_staff_user),
):
    """🆕 v2.1 上传物流并发货。🆕 v2.2 凭后台令牌。"""
    order = _fetch_order(db, order_id)
    order = _map_order_errors(lambda: order_service.ship_order(
        db, order, carrier=body.carrier, tracking_no=body.tracking_no,
        operator_id=user.id, version=body.version,
    ))
    return _order_out(db, order)


@router.post("/orders/{order_id}/accept", response_model=OrderOut)
def accept_order(
    order_id: str,
    body: AcceptRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_staff_user),
):
    """🆕 v2.1 商家验收完结。🆕 v2.2 凭后台令牌。"""
    order = _fetch_order(db, order_id)
    order = _map_order_errors(lambda: order_service.accept_order(
        db, order, operator_id=user.id, version=body.version,
    ))
    return _order_out(db, order)
