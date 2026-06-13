"""设备 API (Spec 4.1)。"""
from __future__ import annotations

from math import ceil
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.camera import Camera, CameraConfig
from app.schemas.camera import (
    CameraBrief,
    CameraDetail,
    CameraListResponse,
    ConfigOut,
)
from app.schemas.common import Pagination

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


@router.get("", response_model=CameraListResponse)
def list_cameras(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    brand: Optional[str] = None,
    db: Session = Depends(get_db),
):
    stmt = select(Camera)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Camera.name.ilike(like), Camera.brand.ilike(like)))
    if brand:
        stmt = stmt.where(Camera.brand == brand)

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()
    rows = db.execute(
        stmt.order_by(Camera.id).offset((page - 1) * limit).limit(limit)
    ).scalars().all()

    return CameraListResponse(
        data=[CameraBrief.model_validate(c, from_attributes=True) for c in rows],
        pagination=Pagination(
            total=total, page=page, limit=limit, pages=ceil(total / limit) if total else 0
        ),
    )


@router.get("/{camera_id}", response_model=CameraDetail)
def get_camera(camera_id: str, db: Session = Depends(get_db)):
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(
            status_code=404,
            detail={"error": "设备不存在", "error_code": "not_found"},
        )
    configs = db.execute(
        select(CameraConfig).where(CameraConfig.camera_id == camera_id)
    ).scalars().all()
    return CameraDetail(
        id=camera.id,
        name=camera.name,
        brand=camera.brand,
        model=camera.model,
        specs=camera.specs or {},
        configurations=[
            ConfigOut(
                id=c.id,
                config_name=c.config_name,
                two_day_price=c.two_day_price,
                three_day_price=c.three_day_price,
                extra_day_price=c.extra_day_price,
                deposit_amount=c.deposit_amount,
                total_units=c.total_units,
                accessories=c.accessories or [],
            )
            for c in configs
        ],
    )


@router.get("/{camera_id}/configs")
def get_camera_configs(camera_id: str, db: Session = Depends(get_db)):
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(
            status_code=404,
            detail={"error": "设备不存在", "error_code": "not_found"},
        )
    configs = db.execute(
        select(CameraConfig).where(CameraConfig.camera_id == camera_id)
    ).scalars().all()
    return {
        "configurations": [
            ConfigOut(
                id=c.id,
                config_name=c.config_name,
                two_day_price=c.two_day_price,
                three_day_price=c.three_day_price,
                extra_day_price=c.extra_day_price,
                deposit_amount=c.deposit_amount,
                total_units=c.total_units,
                accessories=c.accessories or [],
            )
            for c in configs
        ]
    }
