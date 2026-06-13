"""库存 API (Spec 4.2) —— 按日期计算。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.camera import CameraConfig
from app.schemas.inventory import (
    AvailabilityResponse,
    ConfigAvailabilityOut,
    DayAvailabilityOut,
)
from app.services import inventory_service

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


@router.get("/available", response_model=AvailabilityResponse)
def get_available(
    start_date: date = Query(...),
    end_date: date = Query(...),
    camera_config_id: str = Query(default=None),
    db: Session = Depends(get_db),
):
    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail={"error": "start_date 不能晚于 end_date", "error_code": "invalid_range"},
        )
    results = inventory_service.query_availability(
        db, start_date, end_date, camera_config_id
    )
    return AvailabilityResponse(
        query={"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        results=[
            ConfigAvailabilityOut(
                config_id=r.config_id,
                config_name=r.config_name,
                total_units=r.total_units,
                min_available_in_range=r.min_available_in_range,
                daily_breakdown=[
                    DayAvailabilityOut(date=d.day, available=d.available)
                    for d in r.daily_breakdown
                ],
            )
            for r in results
        ],
    )


@router.get("/{config_id}/status")
def get_config_status(config_id: str, db: Session = Depends(get_db)):
    config = db.get(CameraConfig, config_id)
    if not config:
        raise HTTPException(
            status_code=404,
            detail={"error": "配置不存在", "error_code": "not_found"},
        )
    today = date.today()
    avail = inventory_service.get_config_availability(db, config, today, today)
    return {
        "config_id": config.id,
        "config_name": config.config_name,
        "total_units": config.total_units,
        "available_today": avail.min_available_in_range,
        "date": today.isoformat(),
    }
