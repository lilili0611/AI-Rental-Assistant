"""订单租前、租中、租后的陪伴信息与幂等提醒。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.camera import Camera, CameraConfig
from app.models.companion import CompanionEvent, OrderFeedback
from app.models.order import Order, OrderItem
from app.services.device_guides import profile_for


PHASE_LABELS = {
    "pre_rental": "租前准备",
    "in_transit": "运输途中",
    "in_use": "使用陪伴",
    "return_due": "待归还",
    "post_rental": "租后回顾",
    "closed": "已关闭",
}


def derive_phase(order: Order, today: Optional[date] = None) -> str:
    today = today or date.today()
    if order.status == "cancelled":
        return "closed"
    if order.status == "completed":
        return "post_rental"
    if order.status == "returned" or today > order.rental_end:
        return "return_due"
    if order.status == "active" or (
        order.status == "shipped" and order.rental_start <= today <= order.rental_end
    ):
        return "in_use"
    if order.status == "shipped":
        return "in_transit"
    return "pre_rental"


def _event_content(order: Order, event_type: str, today: date) -> tuple[str, str, dict]:
    if event_type == "usage_guide":
        return (
            "设备快速上手",
            "设备已发出。使用前请先检查外观、电池、存储卡和配件，再按设备指南试拍。",
            {"action": "view_companion"},
        )
    if event_type == "logistics_ready":
        return (
            "物流信息已更新",
            f"{order.carrier or '承运商'} 运单 {order.tracking_no or '待补充'}。实时轨迹以承运商信息为准。",
            {"carrier": order.carrier, "tracking_no": order.tracking_no},
        )
    if event_type == "return_reminder":
        delta = (order.rental_end - today).days
        if delta < 0:
            message = f"租期已结束 {abs(delta)} 天，请停止使用并尽快联系客服安排归还。"
        elif delta == 0:
            message = "今天是租期最后一天，请整理设备和全部配件，按约定方式寄回。"
        else:
            message = "明天到期，请提前备份照片、格式化租用的存储卡并保留原包装。"
        return "归还提醒", message, {"days_until_return": delta}
    if event_type == "feedback_invite":
        return "体验反馈", "订单已完成，欢迎评价设备和服务体验，帮助猫猫头继续改进。", {"action": "feedback"}
    return "分享作品", "如果愿意，可以分享使用本设备拍摄的作品，为其他租客提供真实参考。", {"action": "share"}


def _upsert_event(db: Session, order: Order, event_type: str, today: date) -> bool:
    event = db.execute(
        select(CompanionEvent).where(
            CompanionEvent.order_id == order.id,
            CompanionEvent.event_type == event_type,
        )
    ).scalar_one_or_none()
    title, message, payload = _event_content(order, event_type, today)
    if event:
        event.title = title
        event.message = message
        event.payload = payload
        return False
    db.add(
        CompanionEvent(
            order_id=order.id,
            user_id=order.user_id,
            event_type=event_type,
            title=title,
            message=message,
            payload=payload,
            status="unread",
        )
    )
    return True


def ensure_events(db: Session, order: Order, today: Optional[date] = None) -> int:
    """按订单阶段幂等创建/更新陪伴事件，返回新增数量。"""
    today = today or date.today()
    if order.status == "cancelled":
        return 0
    event_types: list[str] = []
    if order.status in {"shipped", "active", "returned"}:
        event_types.append("usage_guide")
    if order.status == "shipped":
        event_types.append("logistics_ready")
    if order.status in {"shipped", "active", "returned"} and today >= order.rental_end - timedelta(days=1):
        event_types.append("return_reminder")
    if order.status == "completed":
        event_types.extend(["feedback_invite", "share_invite"])

    created = sum(1 for event_type in event_types if _upsert_event(db, order, event_type, today))
    if event_types:
        db.commit()
    return created


def _device_guides(db: Session, order: Order) -> list[dict]:
    guides = []
    seen = set()
    for item in order.items:
        row = db.execute(
            select(CameraConfig, Camera)
            .join(Camera, CameraConfig.camera_id == Camera.id)
            .where(CameraConfig.id == item.camera_config_id)
        ).first()
        if not row:
            continue
        config, camera = row
        if camera.id in seen:
            continue
        seen.add(camera.id)
        profile = profile_for(camera.id)
        guides.append(
            {
                "camera_id": camera.id,
                "name": config.config_name,
                "summary": profile["summary"],
                "quick_start": profile["quick_start"],
                "setting_tips": profile["setting_tips"],
                "guide_url": profile["guide_url"],
            }
        )
    return guides


def build_companion(db: Session, order: Order, today: Optional[date] = None) -> dict:
    today = today or date.today()
    ensure_events(db, order, today)
    phase = derive_phase(order, today)
    days_until_return = (order.rental_end - today).days
    if days_until_return < 0:
        return_message = f"已超过归还日 {abs(days_until_return)} 天，请尽快咨询人工处理归还。"
    elif days_until_return == 0:
        return_message = "今天到期，请核对相机、镜头、电池、充电器和存储卡后寄回。"
    else:
        return_message = f"距离归还还有 {days_until_return} 天。到期前一天会生成站内提醒。"

    events = db.execute(
        select(CompanionEvent)
        .where(CompanionEvent.order_id == order.id)
        .order_by(CompanionEvent.created_at.desc())
    ).scalars().all()
    feedback = db.execute(
        select(OrderFeedback).where(OrderFeedback.order_id == order.id)
    ).scalar_one_or_none()
    outlet_keyword = quote("顺丰速运服务点")
    return {
        "order_id": order.id,
        "phase": phase,
        "phase_label": PHASE_LABELS[phase],
        "logistics": {
            "source": "manual",
            "carrier": order.carrier,
            "tracking_no": order.tracking_no,
            "status": "已发货" if order.status == "shipped" else "暂无运输中信息",
            "current_location": None,
            "estimated_delivery": None,
            "updated_at": order.updated_at.isoformat() if order.updated_at else None,
            "notice": "当前展示商家录入的运单，实时轨迹与预计送达待物流服务接入，请以承运商查询为准。",
        },
        "device_guides": _device_guides(db, order),
        "return_guide": {
            "days_until_return": days_until_return,
            "message": return_message,
            "packing_tip": "使用原防震包和纸箱，配件齐全寄回；寄出前备份照片并格式化租用的存储卡。",
            "outlet_query_url": f"https://map.qq.com/?keyword={outlet_keyword}",
            "outlet_notice": "这是腾讯地图搜索入口，并非猫猫头自营网点；寄出前请与人工确认承运方式。",
        },
        "events": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "title": event.title,
                "message": event.message,
                "payload": event.payload or {},
                "status": event.status,
                "created_at": event.created_at,
            }
            for event in events
        ],
        "feedback_submitted": feedback is not None,
    }


def mark_event_read(db: Session, order: Order, event_id: str) -> CompanionEvent:
    event = db.get(CompanionEvent, event_id)
    if not event or event.order_id != order.id:
        raise ValueError("陪伴事件不存在")
    event.status = "read"
    db.commit()
    db.refresh(event)
    return event


def submit_feedback(
    db: Session,
    order: Order,
    rating: int,
    comment: Optional[str],
    share_url: Optional[str],
    showcase_allowed: bool,
) -> OrderFeedback:
    if order.status != "completed":
        raise ValueError("订单完成后才能评价")
    feedback = db.execute(
        select(OrderFeedback).where(OrderFeedback.order_id == order.id)
    ).scalar_one_or_none()
    if not feedback:
        feedback = OrderFeedback(order_id=order.id, user_id=order.user_id, rating=rating)
        db.add(feedback)
    feedback.rating = rating
    feedback.comment = comment.strip() if comment else None
    feedback.share_url = share_url
    feedback.showcase_allowed = bool(showcase_allowed and share_url)
    db.commit()
    db.refresh(feedback)
    return feedback


def showcase(db: Session, limit: int = 20) -> list[dict]:
    feedbacks = db.execute(
        select(OrderFeedback)
        .where(
            OrderFeedback.showcase_allowed.is_(True),
            OrderFeedback.share_url.is_not(None),
        )
        .order_by(OrderFeedback.updated_at.desc())
        .limit(limit)
    ).scalars().all()
    items = []
    for feedback in feedbacks:
        row = db.execute(
            select(CameraConfig, Camera)
            .join(OrderItem, OrderItem.camera_config_id == CameraConfig.id)
            .join(Camera, CameraConfig.camera_id == Camera.id)
            .where(OrderItem.order_id == feedback.order_id)
        ).first()
        camera_name = row[0].config_name if row else "相机设备"
        items.append(
            {
                "camera_name": camera_name,
                "rating": feedback.rating,
                "comment": feedback.comment,
                "share_url": feedback.share_url,
            }
        )
    return items


def sweep_events(db: Session, today: Optional[date] = None) -> dict:
    today = today or date.today()
    orders = db.execute(
        select(Order).where(Order.status.not_in({"cancelled", "draft"}))
    ).scalars().all()
    created = sum(ensure_events(db, order, today) for order in orders)
    return {"orders_scanned": len(orders), "events_created": created}
