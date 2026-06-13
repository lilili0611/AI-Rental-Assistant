"""测试夹具: 独立的内存数据库 + 种子数据。"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 测试隔离: 关闭飞书同步, 避免单元测试真的调用外部飞书 API(慢且污染真实表)
from app.config import settings as _settings
_settings.feishu_enabled = False

from app.models import Base, Camera, CameraConfig, InventoryUnit, User


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def seeded(db):
    """写入 1 个设备 + 1 个配置(3台) + 1 客户。返回常用对象。"""
    cam = Camera(id="R5", name="Canon EOS R5", brand="Canon",
                 daily_price=Decimal("300"), deposit_amount=Decimal("2000"), specs={})
    db.add(cam)
    db.flush()
    cfg = CameraConfig(
        id=str(uuid.uuid4()), camera_id="R5", config_name="R5 + 16-35mm",
        total_units=3, two_day_price=Decimal("200"), three_day_price=Decimal("270"),
        extra_day_price=Decimal("80"), deposit_amount=Decimal("2000"),
        accessories=[],
    )
    db.add(cfg)
    db.flush()
    for i in range(3):
        db.add(InventoryUnit(config_id=cfg.id, unit_label=f"R5-{i}", status="available"))
    user = User(phone="13800000001", name="客户", is_authenticated=True, role="customer")
    staff = User(phone="13900000002", name="员工", role="staff")
    db.add_all([user, staff])
    db.commit()
    return {"camera": cam, "config": cfg, "user": user, "staff": staff}
