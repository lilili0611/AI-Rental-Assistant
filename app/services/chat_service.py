"""对话编排服务 (Spec 4.4 / 6)。

流程: 识别意图 -> 按置信度阈值决策 -> 路由到查询服务 -> 生成回复。
Phase 1: 单轮(无 session 即新建, 不强依赖上下文)。
Phase 2: 维护会话上下文, 合并历史实体, 多轮追踪。

置信度阈值 (Spec 6.2):
  > 0.8: 直接执行
  0.6 - 0.8: 请求用户确认
  < 0.6: 转人工
涉及金钱的意图(下单/改单/取消)即使高置信度也需二次确认。
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.intent import recognizer
from app.intent.recognizer import AUTH_REQUIRED, MONEY_SENSITIVE, IntentResult
from app.models.camera import Camera, CameraConfig
from app.models.conversation import Conversation
from app.services import inventory_service, pricing_service
from app.services.session_store import get_session_store


def _new_session_id() -> str:
    return str(uuid.uuid4())


def _resolve_configs(db: Session, devices: List[str]) -> List[CameraConfig]:
    """根据设备关键词匹配配置。"""
    if not devices:
        return []
    conds = []
    for d in devices:
        like = f"%{d}%"
        conds.append(Camera.id.ilike(like))
        conds.append(Camera.name.ilike(like))
        conds.append(CameraConfig.config_name.ilike(like))
    stmt = (
        select(CameraConfig)
        .join(Camera, CameraConfig.camera_id == Camera.id)
        .where(or_(*conds))
    )
    return list(db.execute(stmt).scalars().unique().all())


# ============ 各意图的处理 ============
def _handle_device_query(db: Session, entities: dict) -> dict:
    devices = entities.get("devices", [])
    configs = _resolve_configs(db, devices) if devices else []
    if not configs:
        cameras = list(db.execute(select(Camera)).scalars().all())
        if not cameras:
            return {"text": "目前还没有上架设备。"}
        lines = ["我们目前提供以下设备："]
        for c in cameras:
            lines.append(f"• {c.name}（{c.brand}）两天 ¥{c.daily_price} 起")
        return {"text": "\n".join(lines)}
    lines = []
    for cfg in configs:
        acc = "、".join(cfg.accessories) if cfg.accessories else "无附加"
        lines.append(
            f"• {cfg.config_name}：两天 ¥{cfg.two_day_price}，"
            f"三天 ¥{cfg.three_day_price}，续租 ¥{cfg.extra_day_price}/天，"
            f"押金 ¥{cfg.deposit_amount}，配件：{acc}"
        )
    return {"text": "为你找到以下配置：\n" + "\n".join(lines)}


def _handle_pricing_query(db: Session, entities: dict) -> dict:
    configs = _resolve_configs(db, entities.get("devices", []))
    if not configs:
        return {"text": "请告诉我你想租哪款设备，我帮你算价格。", "need_more": ["device"]}
    dates = _resolve_period(entities)
    if not dates:
        return {
            "text": f"你想租「{configs[0].config_name}」，请告诉我租期（起止日期或天数），我来算总价。",
            "need_more": ["dates"],
        }
    start, end = dates
    cfg = configs[0]
    price = pricing_service.calculate_price(
        cfg.two_day_price, cfg.three_day_price, cfg.extra_day_price,
        cfg.deposit_amount, start, end,
    )
    text = (
        f"{cfg.config_name} 租 {price.days} 天（{start}~{end}）：\n"
        f"• 计价：{price.basis}\n"
        f"• 租金 ¥{price.rent}\n"
        f"• 押金 ¥{price.deposit}（仅展示，不计入应付）\n"
        f"• 应付租金 ¥{price.total_due}"
    )
    return {
        "text": text,
        "actions": [{"type": "button", "label": "立即下单", "action": "order_create"}],
    }


def _handle_deposit_query(db: Session, entities: dict) -> dict:
    configs = _resolve_configs(db, entities.get("devices", []))
    if not configs:
        return {"text": "请告诉我具体设备，我查一下押金。", "need_more": ["device"]}
    lines = [f"• {c.config_name}：押金 ¥{c.deposit_amount}" for c in configs]
    return {"text": "押金如下：\n" + "\n".join(lines)}


def _handle_inventory_query(db: Session, entities: dict) -> dict:
    configs = _resolve_configs(db, entities.get("devices", []))
    dates = _resolve_period(entities)
    if not dates:
        return {"text": "请告诉我租期的起止日期，我来查这段时间是否有货。", "need_more": ["dates"]}
    start, end = dates
    config_id = configs[0].id if configs else None
    results = inventory_service.query_availability(db, start, end, config_id)
    if not results:
        return {"text": "没有找到匹配的设备配置。"}
    lines = [f"{start} ~ {end} 期间库存："]
    for r in results:
        status = f"可租 {r.min_available_in_range} 台" if r.is_available else "已无货"
        lines.append(f"• {r.config_name}：{status}（共 {r.total_units} 台）")
    return {"text": "\n".join(lines)}


def _resolve_period(entities: dict) -> Optional[tuple]:
    s = entities.get("start_date")
    e = entities.get("end_date")
    if s and e:
        return date.fromisoformat(s), date.fromisoformat(e)
    if s and entities.get("days"):
        start = date.fromisoformat(s)
        return start, start + timedelta(days=int(entities["days"]) - 1)
    return None


_HANDLERS = {
    "device_query": _handle_device_query,
    "device_compare": _handle_device_query,
    "pricing_query": _handle_pricing_query,
    "deposit_query": _handle_deposit_query,
    "inventory_query": _handle_inventory_query,
}


def _persist(db: Session, session_id: str, user_id: Optional[str], round_no: int,
             message: str, response: str, intent: IntentResult) -> None:
    db.add(
        Conversation(
            session_id=session_id,
            user_id=user_id,
            round_number=round_no,
            user_message=message[:1000],
            ai_response=response[:2000],
            detected_intent=intent.intent,
            intent_confidence=Decimal(str(round(intent.confidence, 3))),
            entities=intent.entities,
        )
    )
    db.commit()


def handle_message(
    db: Session,
    message: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    multi_turn: bool = True,
) -> dict:
    """处理一条用户消息, 返回回复结构。"""
    store = get_session_store()
    if not session_id:
        session_id = _new_session_id()
        session = {"session_id": session_id, "user_id": user_id, "round": 0,
                   "history": [], "context": {}, "intents": []}
    else:
        session = store.get(session_id) or {
            "session_id": session_id, "user_id": user_id, "round": 0,
            "history": [], "context": {}, "intents": []
        }

    round_no = session["round"] + 1
    intent = recognizer.recognize(message)

    # 多轮: 合并历史已知实体(如之前提到的设备/日期)
    if multi_turn:
        merged = dict(session.get("context", {}))
        merged.update({k: v for k, v in intent.entities.items() if v})
        intent.entities = merged

    # 决策: 置信度 + 金钱敏感
    decision = _decide(intent)

    if decision == "human":
        text = "这个问题我不太确定，已为你转接人工客服，请稍候。"
        actions = [{"type": "handoff", "label": "转人工", "action": "human_handoff"}]
    elif decision == "confirm":
        text = _confirm_prompt(intent)
        actions = [
            {"type": "button", "label": "是的", "action": f"confirm:{intent.intent}"},
            {"type": "button", "label": "不是", "action": "reject"},
        ]
    elif intent.intent in MONEY_SENSITIVE:
        # 金钱操作即使高置信度也二次确认 (本服务不直接执行下单, 引导到订单 API)
        text = _money_confirm_prompt(intent)
        actions = [
            {"type": "button", "label": "确认", "action": f"confirm:{intent.intent}"},
            {"type": "button", "label": "取消", "action": "reject"},
        ]
    else:
        handler = _HANDLERS.get(intent.intent)
        if handler:
            result = handler(db, intent.entities)
            text = result["text"]
            actions = result.get("actions", [])
        else:
            text = "你好，我是相机租赁助手，可以帮你查设备、库存、价格和下单。"
            actions = []

    # 更新会话
    session["round"] = round_no
    session["history"].append({"role": "user", "content": message})
    session["history"].append({"role": "assistant", "content": text})
    session["context"] = intent.entities
    session["intents"].append(intent.intent)
    if user_id:
        session["user_id"] = user_id
    store.save(session_id, session)

    _persist(db, session_id, user_id, round_no, message, text, intent)

    return {
        "session_id": session_id,
        "round": round_no,
        "detected_intent": intent.intent,
        "confidence": round(intent.confidence, 3),
        "ai_response": text,
        "next_actions": actions,
        "requires_auth": intent.intent in AUTH_REQUIRED,
    }


def _decide(intent: IntentResult) -> str:
    if intent.intent == "unknown" or intent.confidence < 0.6:
        return "human"
    if intent.confidence < 0.8:
        return "confirm"
    return "execute"


def _confirm_prompt(intent: IntentResult) -> str:
    label = {
        "device_query": "查询设备信息",
        "pricing_query": "计算租赁价格",
        "inventory_query": "查询库存",
        "deposit_query": "查询押金",
        "order_create": "创建订单",
        "order_modify": "修改订单",
        "order_cancel": "取消订单",
        "logistics_query": "查询物流",
    }.get(intent.intent, "处理你的请求")
    return f"你是想{label}吗？"


def _money_confirm_prompt(intent: IntentResult) -> str:
    label = {"order_create": "下单", "order_modify": "修改订单", "order_cancel": "取消订单"}.get(
        intent.intent, "执行该操作"
    )
    return f"涉及{label}，请确认后我再为你处理。确认要{label}吗？"
