"""设备操作答疑与不拆机的基础故障排查。"""
from __future__ import annotations

from typing import Optional

from app.intent.recognizer import extract_entities
from app.services.device_guides import profile_for


_DANGER_CUES = ("进水", "泡水", "摔了", "摔坏", "冒烟", "异味", "烫手", "拆机", "拆开", "短路")


def answer(message: str) -> Optional[dict]:
    if any(cue in message for cue in _DANGER_CUES):
        return {
            "text": "请立即关机、断开电源并停止使用，请咨询客服。不要充电、开机或自行拆机。",
            "customer_service": True,
            "actions": [],
        }

    entities = extract_entities(message)
    devices = entities.get("devices", [])
    device_id = devices[0] if devices else None
    if device_id and any(cue in message for cue in ("怎么用", "上手", "教程", "参数", "怎么设置", "拍人像", "拍视频")):
        profile = profile_for(device_id)
        text = (
            f"{device_id}：{profile['summary']}\n"
            f"快速上手：{'；'.join(profile['quick_start'])}\n"
            f"设置建议：{'；'.join(profile['setting_tips'])}"
        )
        actions = []
        if profile.get("guide_url"):
            actions.append(
                {
                    "type": "button",
                    "label": "打开官方指南",
                    "action": "open_url",
                    "payload": {"url": profile["guide_url"]},
                }
            )
        return {"text": text, "customer_service": False, "actions": actions}

    if any(cue in message for cue in ("开不了机", "无法开机", "不能开机", "没反应")):
        return {
            "text": "先关机，重新装入已充电电池并确认电池仓锁紧；仍无反应请停止尝试并咨询客服。",
            "customer_service": False,
            "actions": [],
        }
    if any(cue in message for cue in ("无法对焦", "对不上焦", "对焦失败", "拍糊了")):
        return {
            "text": "确认镜头在AF档，擦净镜头表面，增加环境光并重新半按快门；仍失败请咨询客服。",
            "customer_service": False,
            "actions": [],
        }
    if any(cue in message for cue in ("存储卡错误", "读不到卡", "内存卡错误", "无法保存")):
        return {
            "text": "关机后重新插卡；若卡内有照片先备份，不要直接格式化。换卡仍报错请咨询客服。",
            "customer_service": False,
            "actions": [],
        }
    if any(cue in message for cue in ("电池充不进", "充不了电", "电量掉得快")):
        return {
            "text": "检查充电器、插座和电池触点是否干燥清洁，换插座复测；异常发热请停用并咨询客服。",
            "customer_service": False,
            "actions": [],
        }
    return None
