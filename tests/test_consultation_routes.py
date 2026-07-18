"""四类咨询入口、二级问题和知识库优先规则测试。"""
from __future__ import annotations

import pytest

from app.knowledge_base import guide
from app.schemas.chat import ChatResponse
from app.services import chat_service


@pytest.mark.parametrize(
    ("label", "intent", "route"),
    (
        ("下单问题咨询", "consult_order", "order"),
        ("免押问题咨询", "consult_deposit", "deposit"),
        ("理赔问题咨询", "consult_claim", "claim"),
        ("设备选择咨询", "consult_device", "device"),
    ),
)
def test_consultation_entry_returns_its_route_without_llm(
    db, monkeypatch, label, intent, route
):
    monkeypatch.setattr(guide.llm, "llm_available", lambda: True)
    monkeypatch.setattr(
        guide.llm,
        "chat_completion",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("入口不应调用 LLM")),
    )

    result = chat_service.handle_message(db, label)

    assert result["detected_intent"] == intent
    assert result["answer_source"] == "workflow"
    assert len(result["next_actions"]) == 4
    assert all(action["action"] == "consult_question" for action in result["next_actions"])
    assert all(action["payload"]["route"] == route for action in result["next_actions"])
    ChatResponse.model_validate(result)


def test_route_switch_clears_an_existing_sales_journey(db, seeded):
    started = chat_service.handle_message(db, "我想租相机，帮我推荐")
    assert started["detected_intent"] == "guided_sales"

    switched = chat_service.handle_message(
        db, "理赔问题咨询", session_id=started["session_id"]
    )
    resumed = chat_service.handle_message(
        db, "确认", session_id=started["session_id"]
    )

    assert switched["detected_intent"] == "consult_claim"
    assert resumed["detected_intent"] != "guided_sales"


def test_secondary_question_uses_existing_knowledge_before_llm(db, monkeypatch):
    monkeypatch.setattr(guide.llm, "llm_available", lambda: True)
    monkeypatch.setattr(
        guide.llm,
        "chat_completion",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("知识库命中不应调用 LLM")),
    )
    menu = chat_service.handle_message(db, "免押问题咨询")

    result = chat_service.handle_message(
        db, "免押需要什么条件？", session_id=menu["session_id"]
    )

    assert result["detected_intent"] == "knowledge_qa"
    assert result["answer_source"] == "knowledge_base"
    assert "免押方式（3选1）" in result["ai_response"]


def test_device_route_question_uses_faq_before_guided_sales(db, monkeypatch):
    monkeypatch.setattr(
        guide.llm,
        "chat_completion",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("知识库命中不应调用 LLM")),
    )
    menu = chat_service.handle_message(db, "设备选择咨询")

    result = chat_service.handle_message(
        db,
        "我是新手，去川西旅游，推荐哪款相机？",
        session_id=menu["session_id"],
    )

    assert result["detected_intent"] == "knowledge_qa"
    assert result["answer_source"] == "knowledge_base"
    assert "索尼A7M4" in result["ai_response"]


def test_device_route_can_start_question_driven_sales_journey(db, seeded):
    menu = chat_service.handle_message(db, "设备选择咨询")

    result = chat_service.handle_message(
        db, "开始帮我选设备", session_id=menu["session_id"]
    )

    assert result["detected_intent"] == "guided_sales"
    assert result["answer_source"] == "workflow"
    assert result["ai_response"].count("？") == 1
    assert "主要拍什么" in result["ai_response"]


def test_deposit_credit_freeze_question_is_answered_from_faq(db, monkeypatch):
    monkeypatch.setattr(
        guide.llm,
        "chat_completion",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("知识库命中不应调用 LLM")),
    )

    result = chat_service.handle_message(db, "免押会冻结额度吗？")

    assert result["detected_intent"] == "knowledge_qa"
    assert result["answer_source"] == "knowledge_base"
    assert "押金冻结花呗额度" in result["ai_response"]


def test_order_guide_is_deterministic_and_links_to_device_picker(db, monkeypatch):
    monkeypatch.setattr(
        guide.llm,
        "chat_completion",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("下单指引不应调用 LLM")),
    )

    result = chat_service.handle_message(db, "下单流程是什么？")

    assert result["detected_intent"] == "order_guide"
    assert result["answer_source"] == "business_data"
    assert "查库存 & 算价格" in result["ai_response"]
    assert "填写收货人、手机号、省市区和详细地址" in result["ai_response"]
    assert result["next_actions"][0]["action"] == "scroll_order"
