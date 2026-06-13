"""预留 API (Spec 2.7 / 3.2)。下单前锁定库存 30 分钟。"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_optional_user
from app.database import get_db
from app.models.camera import CameraConfig
from app.models.user import User
from app.services import reservation_service
from app.services.reservation_service import InventoryError

router = APIRouter(prefix="/api/reservations", tags=["reservations"])


class ReservationRequest(BaseModel):
    camera_config_id: str
    quantity: int = Field(default=1, ge=1)
    rental_start: date
    rental_end: date


@router.post("", status_code=201)
def create_reservation(
    body: ReservationRequest,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    config = db.get(CameraConfig, body.camera_config_id)
    if not config:
        raise HTTPException(404, detail={"error": "配置不存在", "error_code": "not_found"})
    if body.rental_end < body.rental_start:
        raise HTTPException(400, detail={"error": "租期结束日不能早于开始日", "error_code": "invalid_period"})
    try:
        r = reservation_service.create_reservation(
            db, config, body.quantity, body.rental_start, body.rental_end,
            user_id=user.id if user else None,
        )
        db.commit()
    except InventoryError as e:
        raise HTTPException(422, detail={"error": e.message, "error_code": "insufficient_inventory", "details": e.details})
    return {
        "reservation_id": r.id,
        "status": r.status,
        "camera_config_id": r.camera_config_id,
        "quantity": r.quantity,
        "rental_start": r.rental_start.isoformat(),
        "rental_end": r.rental_end.isoformat(),
        "expires_at": r.expires_at.isoformat(),
    }
