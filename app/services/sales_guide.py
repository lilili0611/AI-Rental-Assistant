"""猫猫头多轮导购：反问补齐需求、推荐真实配置并带入下单页。"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.intent import recognizer
from app.knowledge_base.faq import load_entries
from app.models.camera import Camera, CameraConfig
from app.services import inventory_service, pricing_service
from app.services.device_guides import profile_for


_START_CUES = (
    "推荐", "怎么选", "哪个好", "对比", "比较", "适合", "想租相机", "租相机", "想租", "帮我选",
    "拍人像", "拍视频", "拍照", "旅游", "旅行", "演唱会", "年会", "宠物",
)

_CONTINUE_DATES = "继续填写租期"
_RESTART_SELECTION = "重新选择设备"
_SIDE_QUESTION_CUES = (
    "？", "?", "吗", "怎么", "为什么", "是什么", "能不能", "可以",
    "推荐", "对比", "比较", "区别", "参数", "适合", "拍人", "拍妹子",
    "人物照", "复古人像", "镜头", "相机",
)

_SCENES = {
    "travel": ("旅游", "旅行", "川西", "风景", "出游"),
    "portrait": (
        "人像", "拍人", "拍妹子", "人物照", "复古人像", "模特", "写真", "服装", "淘宝",
    ),
    "concert": ("演唱会", "舞台", "内场"),
    "video": ("视频", "vlog", "短视频", "走拍", "直播"),
    "event": ("年会", "活动", "会议", "公司记录"),
    "pet": ("宠物", "小猫", "小狗", "动物"),
    "daily": ("日常", "随手拍", "复古", "氛围感"),
}

_SCENE_LABELS = {
    "travel": "旅行风景",
    "portrait": "人像写真",
    "concert": "演唱会舞台",
    "video": "Vlog视频",
    "event": "活动年会",
    "pet": "宠物抓拍",
    "daily": "日常氛围",
}

_SCENE_CAMERA_IDS = {
    "travel": ["G7X2", "XM5", "R10"],
    "portrait": ["XM5", "R10", "G7X2"],
    "concert": ["XM5", "R10"],
    "video": ["POCKET3", "XM5", "G7X2"],
    "event": ["R10", "XM5", "G7X2"],
    "pet": ["R10", "XM5"],
    "daily": ["G7X2", "U400", "IXUS110", "U1"],
}


def should_start(message: str) -> bool:
    lower = message.lower()
    return any(cue in lower for cue in _START_CUES)


def _awaiting_dates(journey: dict) -> bool:
    return bool(
        journey.get("active")
        and journey.get("recommended")
        and (not journey.get("start_date") or not journey.get("end_date"))
    )


def is_side_question(message: str, journey: dict) -> bool:
    """等待租期时识别插入的新问题，日期或控制动作仍交给导购状态机。"""
    if not _awaiting_dates(journey):
        return False
    if _CONTINUE_DATES in message or _RESTART_SELECTION in message:
        return False
    entities = recognizer.extract_entities(message)
    if any(entities.get(key) for key in ("start_date", "end_date", "days")):
        return False
    return bool(journey.get("paused")) or any(cue in message for cue in _SIDE_QUESTION_CUES)


def detour_actions() -> list[dict]:
    return [
        {"type": "button", "label": _CONTINUE_DATES, "action": "guide_choice"},
        {"type": "button", "label": _RESTART_SELECTION, "action": "guide_choice"},
    ]


def append_detour_actions(actions: list[dict]) -> list[dict]:
    result = list(actions)
    existing = {action.get("label") for action in result}
    result.extend(action for action in detour_actions() if action["label"] not in existing)
    return result


def _extract_scene(message: str) -> Optional[str]:
    lower = message.lower()
    for scene, aliases in _SCENES.items():
        if any(alias in lower for alias in aliases):
            return scene
    return None


def _extract_experience(message: str) -> Optional[str]:
    if any(cue in message for cue in ("新手", "第一次", "不会用", "小白", "没用过")):
        return "beginner"
    if any(cue in message for cue in ("有基础", "会用", "熟悉", "进阶", "专业")):
        return "experienced"
    return None


def _extract_priority(message: str) -> Optional[str]:
    if any(cue in message for cue in ("省钱", "预算有限", "便宜", "性价比")):
        return "budget"
    if any(cue in message for cue in ("画质优先", "画质最好", "专业", "效果优先")):
        return "quality"
    if any(cue in message for cue in ("均衡", "平衡", "都兼顾", "适中")):
        return "balanced"
    return None


def _extract_deposit_choice(message: str) -> Optional[bool]:
    if any(cue in message for cue in ("不需要免押", "不用免押", "直接付押金", "不免押")):
        return False
    if any(cue in message for cue in ("需要免押", "要免押", "申请免押", "想免押")):
        return True
    return None


def _faq_answer(entry_id: str) -> str:
    return next(entry.answer for entry in load_entries() if entry.entry_id == entry_id)


def _configs_for_journey(db: Session, journey: dict) -> list[tuple[CameraConfig, Camera]]:
    requested = journey.get("requested_devices") or []
    camera_ids = requested or _SCENE_CAMERA_IDS.get(journey.get("scene"), [])
    rows = db.execute(
        select(CameraConfig, Camera)
        .join(Camera, CameraConfig.camera_id == Camera.id)
        .where(Camera.id.in_(camera_ids))
    ).all() if camera_ids else []
    if not rows:
        rows = db.execute(
            select(CameraConfig, Camera).join(Camera, CameraConfig.camera_id == Camera.id)
        ).all()
        # 测试环境或小库存门店可能没有场景映射中的机型；此时从真实在售配置中推荐，
        # 不能继续按原映射 ID 过滤而误报“无可推荐配置”。
        camera_ids = list(dict.fromkeys(camera.id for _, camera in rows))

    # 同一机身根据场景/偏好挑一个配置。
    grouped: dict[str, list[tuple[CameraConfig, Camera]]] = {}
    for config, camera in rows:
        grouped.setdefault(camera.id, []).append((config, camera))
    picked = []
    for camera_id in camera_ids or grouped.keys():
        options = grouped.get(camera_id, [])
        if not options:
            continue
        if camera_id == "XM5":
            if journey.get("scene") in {"travel", "concert"}:
                preferred = next((row for row in options if "18-300" in row[0].config_name), None)
            elif journey.get("priority") == "quality" or journey.get("scene") in {"portrait", "event", "pet"}:
                preferred = next((row for row in options if "18-50" in row[0].config_name), None)
            else:
                preferred = next((row for row in options if "15-45" in row[0].config_name), None)
            picked.append(preferred or options[0])
        else:
            picked.append(options[0])

    reverse = journey.get("priority") == "quality"
    picked.sort(key=lambda row: row[0].three_day_price, reverse=reverse)
    return picked[:2]


def _comparison(rows: list[tuple[CameraConfig, Camera]]) -> str:
    lines = []
    for config, camera in rows:
        profile = profile_for(camera.id)
        lines.append(
            f"• {config.config_name}：{profile['strengths']}；两天¥{config.two_day_price}，"
            f"三天¥{config.three_day_price}，续租¥{config.extra_day_price}/天"
        )
    return "\n".join(lines)


def _prefill_action(journey: dict) -> dict:
    return {
        "type": "button",
        "label": "带入下单页",
        "action": "prefill_order",
        "payload": {
            "camera_id": journey["camera_id"],
            "config_id": journey["config_id"],
            "start_date": journey["start_date"],
            "end_date": journey["end_date"],
            "quantity": journey.get("quantity", 1),
        },
    }


def process(db: Session, message: str, journey: dict) -> Optional[dict]:
    """处理一轮导购。未处于导购且无启动信号时返回 None。"""
    if _RESTART_SELECTION in message:
        journey.clear()
        journey["active"] = True
    elif _CONTINUE_DATES in message:
        journey.pop("paused", None)
    elif "重新推荐" in message:
        journey.clear()
    # 上一轮已完成后，新的推荐请求应开启全新需求收集，避免沿用旧设备和租期。
    elif not journey.get("active") and journey.get("config_id") and should_start(message):
        journey.clear()
    if "换备选" in message:
        journey["selected_index"] = int(journey.get("selected_index", 0)) + 1
        journey.pop("deposit_choice", None)
    if "换日期" in message and not recognizer.extract_entities(message).get("start_date"):
        journey.pop("start_date", None)
        journey.pop("end_date", None)
        journey.pop("deposit_choice", None)
    if not journey.get("active") and not should_start(message):
        return None
    journey["active"] = True

    scene = _extract_scene(message)
    experience = _extract_experience(message)
    priority = _extract_priority(message)
    deposit_choice = _extract_deposit_choice(message)
    entities = recognizer.extract_entities(message)
    if any(entities.get(key) for key in ("start_date", "end_date", "days")):
        journey.pop("paused", None)
    if scene:
        journey["scene"] = scene
    if experience:
        journey["experience"] = experience
    if priority:
        journey["priority"] = priority
    if deposit_choice is not None:
        journey["deposit_choice"] = deposit_choice
    if entities.get("devices"):
        journey["requested_devices"] = entities["devices"]
    for key in ("start_date", "end_date", "quantity"):
        if entities.get(key):
            journey[key] = entities[key]

    if not journey.get("scene") and len(journey.get("requested_devices", [])) >= 2 and not journey.get("compared"):
        compare_rows = _configs_for_journey(db, journey)
        journey["compared"] = True
        return {
            "text": f"先看实际在售配置：\n{_comparison(compare_rows)}\n你主要拍什么场景？我再帮你选更合适的一款。",
            "actions": [],
            "journey": journey,
        }
    if not journey.get("scene"):
        return {
            "text": "先告诉我主要拍什么：旅行风景、人像、演唱会、Vlog、活动还是日常记录？",
            "actions": [
                {"type": "button", "label": label, "action": "guide_choice"}
                for label in ("旅行风景", "人像写真", "演唱会", "Vlog视频")
            ],
            "journey": journey,
        }
    if not journey.get("experience"):
        return {
            "text": f"明白，主要拍{_SCENE_LABELS[journey['scene']]}。你是第一次用相机，还是已有基础？",
            "actions": [
                {"type": "button", "label": "第一次用相机", "action": "guide_choice"},
                {"type": "button", "label": "已有基础", "action": "guide_choice"},
            ],
            "journey": journey,
        }
    if not journey.get("priority"):
        return {
            "text": "选设备时你更看重省钱、轻便均衡，还是画质优先？",
            "actions": [
                {"type": "button", "label": "预算有限，优先省钱", "action": "guide_choice"},
                {"type": "button", "label": "轻便和画质均衡", "action": "guide_choice"},
                {"type": "button", "label": "画质优先", "action": "guide_choice"},
            ],
            "journey": journey,
        }

    rows = _configs_for_journey(db, journey)
    if not rows:
        journey["active"] = False
        return {"text": "目前没有可推荐的在售配置，请咨询客服。", "actions": [], "journey": journey}
    selected_index = int(journey.get("selected_index", 0)) % len(rows)
    selected_config, selected_camera = rows[selected_index]
    journey["camera_id"] = selected_camera.id
    journey["config_id"] = selected_config.id
    journey["recommendation_ids"] = [config.id for config, _ in rows]

    if not journey.get("recommended"):
        journey["recommended"] = True
        return {
            "text": (
                f"按你的需求，我先比较这两款：\n{_comparison(rows)}\n"
                f"我更推荐「{selected_config.config_name}」。你计划哪天开始、哪天归还？"
            ),
            "actions": [],
            "journey": journey,
        }

    if not journey.get("start_date") or not journey.get("end_date"):
        return {
            "text": "请告诉我起租日和归还日，例如“7月20日到7月22日”，我马上查库存和租金。",
            "actions": [],
            "journey": journey,
        }

    start = date.fromisoformat(journey["start_date"])
    end = date.fromisoformat(journey["end_date"])
    if end < start:
        journey.pop("end_date", None)
        return {"text": "归还日不能早于起租日，请重新告诉我租期。", "actions": [], "journey": journey}

    quantity = int(journey.get("quantity", 1))
    available = inventory_service.get_config_availability(db, selected_config, start, end)
    if available.min_available_in_range < quantity:
        return {
            "text": f"这段时间「{selected_config.config_name}」库存不足。你想换备选设备，还是换一组日期？",
            "actions": [
                {"type": "button", "label": "换备选设备", "action": "guide_choice"},
                {"type": "button", "label": "我换日期", "action": "guide_choice"},
            ],
            "journey": journey,
        }

    price = pricing_service.calculate_price(
        selected_config.two_day_price,
        selected_config.three_day_price,
        selected_config.extra_day_price,
        selected_config.deposit_amount,
        start,
        end,
    )
    if "deposit_choice" not in journey:
        return {
            "text": (
                f"有货：{selected_config.config_name}，租{price.days}天，租金¥{price.rent}，"
                f"押金参考¥{price.deposit}。是否需要申请免押？"
            ),
            "actions": [
                {"type": "button", "label": "需要免押", "action": "guide_choice"},
                {"type": "button", "label": "不需要免押", "action": "guide_choice"},
            ],
            "journey": journey,
        }

    if journey["deposit_choice"]:
        prefix = f"可以，免押说明如下：\n{_faq_answer('1')}\n"
    else:
        prefix = "好的，按普通押金方式继续。\n"
    journey["active"] = False
    return {
        "text": prefix + "设备、租期和数量已经整理好，点击“带入下单页”核对库存与价格，再由你确认下单。",
        "actions": [_prefill_action(journey)],
        "journey": journey,
    }
