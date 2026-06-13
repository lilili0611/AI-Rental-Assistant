"""价格 API (Spec 4.3)。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.camera import CameraConfig
from app.schemas.inventory import PricingResponse
from app.services import pricing_service

router = APIRouter(prefix="/api/pricing", tags=["pricing"])


@router.get("/calculate", response_model=PricingResponse)
def calculate(
    camera_config_id: str = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    coupon_code: str = Query(default=None),
    db: Session = Depends(get_db),
):
    if end_date < start_date:
        raise HTTPException(
            status_code=400,
            detail={"error": "租期至少 1 天", "error_code": "invalid_period"},
        )
    config = db.get(CameraConfig, camera_config_id)
    if not config:
        raise HTTPException(
            status_code=404,
            detail={"error": "配置不存在", "error_code": "not_found"},
        )
    p = pricing_service.calculate_price(
        config.two_day_price, config.three_day_price, config.extra_day_price,
        config.deposit_amount, start_date, end_date,
    )
    return PricingResponse(
        device=config.config_name,
        rental_period={
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": p.days,
        },
        pricing={
            "basis": p.basis,
            "two_day_price": float(p.two_day_price),
            "three_day_price": float(p.three_day_price),
            "extra_day_price": float(p.extra_day_price),
            "extra_days": p.extra_days,
            "rent": float(p.rent),
        },
        deposit=p.deposit,
        total_due=p.total_due,
    )
