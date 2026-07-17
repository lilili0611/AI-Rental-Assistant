"""订单全流程陪伴、评价与作品展示 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models.order import Order
from app.models.user import User
from app.schemas.companion import CompanionOut, FeedbackOut, FeedbackRequest, ShowcaseItem
from app.services import companion_service

router = APIRouter(prefix="/api", tags=["companion"])


def _owned_order(db: Session, order_id: str, user: User) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, detail={"error": "订单不存在", "error_code": "not_found"})
    if order.user_id != user.id:
        raise HTTPException(403, detail={"error": "无权访问该订单", "error_code": "forbidden"})
    return order


@router.get("/orders/{order_id}/companion", response_model=CompanionOut)
def get_companion(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return companion_service.build_companion(db, _owned_order(db, order_id, user))


@router.post("/orders/{order_id}/companion/events/{event_id}/read")
def read_event(
    order_id: str,
    event_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = _owned_order(db, order_id, user)
    try:
        event = companion_service.mark_event_read(db, order, event_id)
    except ValueError as exc:
        raise HTTPException(404, detail={"error": str(exc), "error_code": "not_found"})
    return {"ok": True, "event_id": event.id, "status": event.status}


@router.post("/orders/{order_id}/feedback", response_model=FeedbackOut)
def submit_feedback(
    order_id: str,
    body: FeedbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = _owned_order(db, order_id, user)
    try:
        feedback = companion_service.submit_feedback(
            db,
            order,
            rating=body.rating,
            comment=body.comment,
            share_url=str(body.share_url) if body.share_url else None,
            showcase_allowed=body.showcase_allowed,
        )
    except ValueError as exc:
        raise HTTPException(409, detail={"error": str(exc), "error_code": "invalid_state"})
    return FeedbackOut(
        order_id=feedback.order_id,
        rating=feedback.rating,
        comment=feedback.comment,
        share_url=feedback.share_url,
        showcase_allowed=feedback.showcase_allowed,
    )


@router.get("/community/showcase", response_model=list[ShowcaseItem])
def community_showcase(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return companion_service.showcase(db, limit=limit)
