"""损坏赔付知识：展示业务方扣费标准图，不由 AI 自动定损。"""
from __future__ import annotations

from typing import Optional


DAMAGE_STANDARD_URL = "/static/damage-fee-standard.jpg"

_DAMAGE_CUES = (
    "赔付", "赔偿", "扣费", "扣押金", "定损", "维修费", "划痕", "掉漆",
    "磕碰", "磨损", "凹痕", "裂痕", "镜片凹坑", "uv镜", "UV镜", "首次拆修",
)
_ACCIDENT_CUES = ("摔坏", "摔了", "碰撞", "磕坏", "砸坏")
_OUTSIDE_IMAGE_CUES = ("进水", "遗失", "丢失", "被盗", "意外保障", "保险理赔")


def answer(message: str) -> Optional[dict]:
    """命中损坏政策时返回标准图入口；最终金额留给实物验收与客服确认。"""
    if any(cue in message for cue in _OUTSIDE_IMAGE_CUES):
        return None
    if not any(cue in message for cue in _DAMAGE_CUES + _ACCIDENT_CUES):
        return None

    if any(cue in message for cue in _ACCIDENT_CUES):
        prefix = "请先关机并停止使用，不要继续通电或自行拆机。"
    else:
        prefix = "相机磕碰磨损扣费标准见图。"
    return {
        "text": prefix + "最终损坏类型、尺寸和扣费金额以归还验收及客服确认为准。",
        "actions": [
            {
                "type": "button",
                "label": "查看扣费标准图",
                "action": "open_url",
                "payload": {"url": DAMAGE_STANDARD_URL},
            }
        ],
    }
