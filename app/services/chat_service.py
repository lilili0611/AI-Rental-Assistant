"""对话编排服务 (Spec 4.4 / 6)。

流程: 不合理请求检测 -> FAQ 知识库 -> 结构化业务意图 -> LLM 短回复兜底。
Phase 1: 单轮(无 session 即新建, 不强依赖上下文)。
Phase 2: 维护会话上下文, 合并历史实体, 多轮追踪。

置信度阈值 (Spec 6.2):
  > 0.8: 直接执行
  0.6 - 0.8: 请求用户确认
  < 0.6: 提示咨询客服
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
from app.knowledge_base import faq, guide
from app.models.camera import Camera, CameraConfig
from app.models.conversation import Conversation
from app.services import (
    consultation_routes,
    damage_support,
    inventory_service,
    pricing_service,
    sales_guide,
    usage_support,
)
from app.services.session_store import get_session_store


def _new_session_id() -> str:
    return str(uuid.uuid4())


def _empty_session(session_id: str, user_id: Optional[str]) -> dict:
    return {
        "session_id": session_id,
        "user_id": user_id,
        "round": 0,
        "history": [],
        "context": {},
        "intents": [],
        "sales_journey": {},
    }


def _restore_session(db: Session, session_id: str, user_id: Optional[str]) -> dict:
    """Vercel 多实例下进程内会话丢失时，从持久化对话恢复最近上下文。"""
    rows = db.execute(
        select(Conversation)
        .where(Conversation.session_id == session_id)
        .order_by(Conversation.round_number.desc())
        .limit(5)
    ).scalars().all()
    if not rows:
        return _empty_session(session_id, user_id)
    rows.reverse()
    last = rows[-1]
    last_entities = last.entities or {}
    return {
        "session_id": session_id,
        "user_id": user_id or last.user_id,
        "round": last.round_number,
        "history": [
            item
            for row in rows
            for item in (
                {"role": "user", "content": row.user_message or ""},
                {"role": "assistant", "content": row.ai_response or ""},
            )
        ],
        "context": last_entities,
        "intents": [row.detected_intent for row in rows if row.detected_intent],
        "sales_journey": dict(last_entities.get("sales_journey", {})),
    }


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
        session = _empty_session(session_id, user_id)
    else:
        session = store.get(session_id) or _restore_session(db, session_id, user_id)

    safe_message = sales_guide.redact_shipping_message(message)
    round_no = session["round"] + 1
    actions = []
    answer_source = "business_data"

    unreasonable = guide.is_unreasonable(message)
    consultation = consultation_routes.enter(message) if not unreasonable else None
    common_answer = (
        consultation_routes.answer_common(message)
        if not unreasonable and consultation is None
        else None
    )
    sales_journey = session.setdefault("sales_journey", {})
    side_question = (
        sales_guide.is_side_question(message, sales_journey)
        if not unreasonable and consultation is None
        else False
    )

    # 1. 不合理请求优先拦截，不进入知识库或 LLM，也不提供转接动作。
    if unreasonable:
        intent = IntentResult(intent="customer_service", confidence=1.0, source="rule")
        text = guide.CUSTOMER_SERVICE_RESPONSE
        actions = []
        answer_source = "customer_service"
    # 2. 四类一级咨询入口只做确定性导航，不调用 LLM。
    elif consultation:
        session["sales_journey"] = {}
        intent = IntentResult(
            intent=consultation["intent"],
            confidence=1.0,
            entities={"consultation_route": consultation["route"]},
            source="workflow",
        )
        text = consultation["text"]
        actions = consultation["actions"]
        answer_source = "workflow"
    # 3. 补齐页面能力可确定回答、但 FAQ 未覆盖的下单指引。
    elif common_answer:
        intent = IntentResult(
            intent=common_answer["intent"],
            confidence=1.0,
            entities={"consultation_route": "order"},
            source="business_data",
        )
        text = common_answer["text"]
        actions = common_answer["actions"]
        answer_source = "business_data"
    else:
        # 4. 损坏与赔付问题优先展示业务方标准图，不由 AI 自动定损。
        damage = damage_support.answer(message)
        if damage:
            intent = IntentResult(
                intent="damage_policy",
                confidence=0.95,
                entities={},
                source="knowledge_base",
            )
            text = damage["text"]
            actions = damage.get("actions", [])
            answer_source = "knowledge_base"
        else:
            # 3. 设备操作与简单故障排查；危险情况提示停用并咨询客服。
            support = usage_support.answer(message)
            if support:
                intent = IntentResult(
                    intent="usage_support",
                    confidence=0.95,
                    entities={},
                    source="knowledge_base",
                )
                text = support["text"]
                actions = support.get("actions", [])
                answer_source = (
                    "customer_service"
                    if support.get("customer_service")
                    else "knowledge_base"
                )
            else:
                # 6. 客服知识库优先，命中时原样返回，不调用导购流程或 LLM 润色。
                knowledge_match = faq.search(message)
                if knowledge_match:
                    intent = IntentResult(
                        intent="knowledge_qa",
                        confidence=knowledge_match.score,
                        entities={"knowledge_entry_id": knowledge_match.entry.entry_id},
                        source="knowledge_base",
                    )
                    text = knowledge_match.entry.answer
                    answer_source = "knowledge_base"
                else:
                    # 7. 等待租期时的新问题暂停导购，直接进入 LLM 安全兜底。
                    if side_question:
                        text, actions, answer_source = _fallback_or_customer_service(
                            safe_message, session.get("history", []), side_question=True
                        )
                        intent = IntentResult(
                            intent="guided_sales_side_question",
                            confidence=0.95,
                            entities={},
                            source=answer_source,
                        )
                    else:
                        # 8. 知识库未覆盖的选购需求进入主动导购，每轮只反问一个信息。
                        guided = sales_guide.process(db, message, sales_journey)
                    if not side_question and guided:
                        session["sales_journey"] = guided["journey"]
                        intent = IntentResult(
                            intent="guided_sales",
                            confidence=0.95,
                            entities={"sales_journey": guided["journey"]},
                            source="workflow",
                        )
                        text = guided["text"]
                        actions = guided.get("actions", [])
                        answer_source = "workflow"
                    elif not side_question:
                        # 9. 设备、实时库存、价格与订单继续走结构化业务能力。
                        intent = recognizer.recognize(safe_message)
                        if multi_turn:
                            merged = {
                                k: v for k, v in session.get("context", {}).items()
                                if k != "sales_journey"
                            }
                            merged.update({k: v for k, v in intent.entities.items() if v})
                            intent.entities = merged

                        decision = _decide(intent)
                        if decision == "customer_service":
                            text, actions, answer_source = _fallback_or_customer_service(
                                safe_message, session.get("history", [])
                            )
                        elif decision == "confirm":
                            text = _confirm_prompt(intent)
                            actions = [
                                {"type": "button", "label": "是的", "action": f"confirm:{intent.intent}"},
                                {"type": "button", "label": "不是", "action": "reject"},
                            ]
                        elif intent.intent in MONEY_SENSITIVE:
                            text = _money_confirm_prompt(intent)
                            actions = [
                                {"type": "button", "label": "确认", "action": f"confirm:{intent.intent}"},
                                {"type": "button", "label": "取消", "action": "reject"},
                            ]
                        else:
                            handler = _HANDLERS.get(intent.intent)
                            if _is_general_shopping_question(message, intent):
                                text, actions, answer_source = _fallback_or_customer_service(
                                    safe_message, session.get("history", [])
                                )
                            elif handler:
                                result = handler(db, intent.entities)
                                text = result["text"]
                                actions = result.get("actions", [])
                            else:
                                text, actions, answer_source = _fallback_or_customer_service(
                                    safe_message, session.get("history", [])
                                )

    # 发散问题回答后暂停但保留导购草稿，并提供恢复/重选动作。
    if side_question:
        sales_journey["paused"] = True
        actions = sales_guide.append_detour_actions(actions)
        intent.entities = {**intent.entities, "sales_journey": dict(sales_journey)}

    # 更新会话
    session["round"] = round_no
    session["history"].append({"role": "user", "content": safe_message})
    session["history"].append({"role": "assistant", "content": text})
    session["context"] = intent.entities
    session["intents"].append(intent.intent)
    if user_id:
        session["user_id"] = user_id
    store.save(session_id, session)

    _persist(db, session_id, user_id, round_no, safe_message, text, intent)

    return {
        "session_id": session_id,
        "round": round_no,
        "detected_intent": intent.intent,
        "confidence": round(intent.confidence, 3),
        "ai_response": text,
        "answer_source": answer_source,
        "next_actions": actions,
        "requires_auth": intent.intent in AUTH_REQUIRED,
    }


def _fallback_or_customer_service(
    message: str,
    history: list[dict],
    side_question: bool = False,
) -> tuple[str, list[dict], str]:
    body = guide.generate_answer(message, history, side_question=side_question)
    if body:
        return guide.mark_ai_generated(body), [], "llm"
    return (
        guide.CUSTOMER_SERVICE_RESPONSE,
        [],
        "customer_service",
    )


def _is_general_shopping_question(message: str, intent: IntentResult) -> bool:
    """无明确在售型号的场景选购问题，应交给导购而不是列出全部设备。"""
    if intent.intent not in {"device_query", "device_compare"}:
        return False
    if intent.entities.get("devices"):
        return False
    shopping_cues = ("怎么选", "推荐", "适合", "哪个好", "拍摄", "拍", "场景", "搭配", "新手")
    return any(cue in message for cue in shopping_cues)


def _decide(intent: IntentResult) -> str:
    if intent.intent == "unknown" or intent.confidence < 0.6:
        return "customer_service"
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
