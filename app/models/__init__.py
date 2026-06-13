"""ORM 模型包。导入全部模型以便 Base.metadata 建表。"""
from app.models.base import Base
from app.models.user import User, UserAddress
from app.models.camera import Camera, CameraConfig
from app.models.inventory import InventoryUnit, Occupancy
from app.models.order import Order, OrderItem, OrderChange
from app.models.reservation import Reservation
from app.models.conversation import Conversation

__all__ = [
    "Base",
    "User",
    "UserAddress",
    "Camera",
    "CameraConfig",
    "InventoryUnit",
    "Occupancy",
    "Order",
    "OrderItem",
    "OrderChange",
    "Reservation",
    "Conversation",
]
