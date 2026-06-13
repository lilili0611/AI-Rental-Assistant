"""初始化演示数据 —— 业务方真实设备目录与档位价格。

用法:
    source .venv/bin/activate
    python -m scripts.seed_data

价格为「两天/三天/三天以上续租(元/天)」三档。押金暂为 0(待业务方押金表)。
重复运行会先清空相关表再写入。
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from app.database import SessionLocal, engine
from app.models import Base, Camera, CameraConfig, InventoryUnit, User


def D(x):
    return Decimal(str(x))


# (camera_id, 名称, 品牌, [配置: (配置名, 台数, 两天, 三天, 续租, 押金, 配件)])
CATALOG = [
    ("G12", "佳能 G12", "Canon", [
        ("佳能G12", 1, 100, 120, 25, 5700, [])]),
    ("G7X2", "佳能 G7X2", "Canon", [
        ("佳能G7X2", 3, 120, 140, 30, 5700, [])]),
    ("R10", "佳能 R10", "Canon", [
        ("佳能R10", 1, 120, 140, 30, 5800, [])]),
    ("POCKET3", "DJI POCKET3", "DJI", [
        ("DJI POCKET3", 1, 60, 90, 10, 3000, [])]),
    ("FLIP", "DJI FLIP", "DJI", [
        ("DJI FLIP", 1, 60, 90, 10, 2000, [])]),
    ("XM5", "富士 XM5", "Fujifilm", [
        ("富士XM5 + 富士15-45", 1, 130, 150, 30, 5500, ["富士 XF 15-45mm"]),
        ("富士XM5 + 适马18-50", 1, 190, 220, 35, 7700, ["适马 18-50mm f/2.8"]),
        ("富士XM5 + 腾龙18-300", 1, 190, 220, 35, 7700, ["腾龙 18-300mm"])]),
    ("A620", "佳能 A620", "Canon", [
        ("佳能A620", 1, 50, 60, 18, 1800, [])]),
    ("IXUS110", "佳能 IXUS110", "Canon", [
        ("佳能IXUS110", 1, 50, 60, 18, 1800, [])]),
    ("U300", "奥林巴斯 U300", "Olympus", [
        ("奥林巴斯U300", 1, 50, 60, 16, 900, [])]),
    ("U400", "奥林巴斯 U400", "Olympus", [
        ("奥林巴斯U400", 1, 55, 66, 18, 900, [])]),
    ("U1", "奥林巴斯 U1 定焦", "Olympus", [
        ("奥林巴斯U1 定焦", 1, 50, 55, 5, 800, [])]),
]


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        db.query(InventoryUnit).delete()
        db.query(CameraConfig).delete()
        db.query(Camera).delete()
        db.query(User).delete()
        db.commit()

        for cam_id, name, brand, configs in CATALOG:
            start_price = min(c[2] for c in configs)  # 列表展示"两天起"价
            db.add(Camera(
                id=cam_id, name=name, brand=brand, model=name,
                daily_price=D(start_price), deposit_amount=D(0), specs={},
            ))
            db.flush()
            for cfg_name, units, two, three, extra, deposit, acc in configs:
                cfg = CameraConfig(
                    id=str(uuid.uuid4()), camera_id=cam_id, config_name=cfg_name,
                    total_units=units, two_day_price=D(two), three_day_price=D(three),
                    extra_day_price=D(extra), deposit_amount=D(deposit), accessories=acc,
                )
                db.add(cfg)
                db.flush()
                for i in range(units):
                    db.add(InventoryUnit(
                        config_id=cfg.id, unit_label=f"{cam_id}-{i + 1:02d}",
                        status="available",
                    ))

        customer = User(phone="13800000001", name="测试客户",
                        is_authenticated=True, role="customer")
        staff = User(phone="13900000002", name="仓库小王", role="staff")
        db.add_all([customer, staff])
        db.commit()

        n_cam = db.query(Camera).count()
        n_cfg = db.query(CameraConfig).count()
        n_unit = db.query(InventoryUnit).count()
        print(f"✅ 演示数据已写入: {n_cam} 个设备 / {n_cfg} 个配置 / {n_unit} 台实物")
        print(f"   客户 X-User-Id: {customer.id}  phone={customer.phone}")
        print(f"   员工 X-User-Id: {staff.id}  phone={staff.phone}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
