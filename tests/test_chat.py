"""聊天服务关键路径测试。"""
from __future__ import annotations

from datetime import date, timedelta

from app.config import settings
from app.intent.recognizer import IntentResult
from app.knowledge_base import guide
from app.services import chat_service
from app.services.session_store import get_session_store


def test_device_query_for_config_uses_tier_prices(db, seeded, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "")

    result = chat_service.handle_message(db, "R5 有什么配置")

    assert result["detected_intent"] == "device_query"
    assert "R5 + 16-35mm" in result["ai_response"]
    assert "两天" in result["ai_response"]
    assert "三天" in result["ai_response"]
    assert "续租" in result["ai_response"]


def _mock_inventory_intent(monkeypatch, start: date, end: date, quantity: int = 1):
    monkeypatch.setattr(guide.llm, "llm_available", lambda: False)
    monkeypatch.setattr(chat_service.sales_guide, "process", lambda *args: None)
    monkeypatch.setattr(
        chat_service.recognizer,
        "recognize",
        lambda message: IntentResult(
            intent="inventory_query",
            confidence=0.9,
            entities={
                "devices": ["R5"],
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "quantity": quantity,
            },
            source="rule",
        ),
    )


def test_inventory_result_offers_direct_checkout_and_affirmation_keeps_context(
    db, seeded, monkeypatch
):
    start = date.today() + timedelta(days=1)
    end = date.today() + timedelta(days=2)
    _mock_inventory_intent(monkeypatch, start, end)

    first = chat_service.handle_message(db, "租佳能R5明后天")

    assert first["detected_intent"] == "inventory_query"
    assert first["next_actions"][0]["label"] == "下单"
    assert first["next_actions"][0]["action"] == "prefill_order"
    assert first["next_actions"][0]["payload"] == {
        "camera_id": seeded["camera"].id,
        "config_id": seeded["config"].id,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "quantity": 1,
    }

    confirmed = chat_service.handle_message(db, "对", session_id=first["session_id"])

    assert confirmed["detected_intent"] == "checkout_confirmed"
    assert confirmed["answer_source"] == "workflow"
    assert "已确认" in confirmed["ai_response"]
    assert confirmed["next_actions"][0]["label"] == "下单"
    assert confirmed["next_actions"][0]["payload"] == first["next_actions"][0]["payload"]


def test_checkout_confirmation_restores_candidate_from_database(db, seeded, monkeypatch):
    start = date.today() + timedelta(days=3)
    end = start + timedelta(days=1)
    _mock_inventory_intent(monkeypatch, start, end)
    first = chat_service.handle_message(db, "R5这两天有货吗")

    get_session_store().delete(first["session_id"])
    restored = chat_service.handle_message(db, "是的", session_id=first["session_id"])

    assert restored["round"] == 2
    assert restored["detected_intent"] == "checkout_confirmed"
    assert restored["next_actions"][0]["action"] == "prefill_order"


def test_negative_reply_clears_checkout_candidate(db, seeded, monkeypatch):
    start = date.today() + timedelta(days=5)
    end = start + timedelta(days=1)
    _mock_inventory_intent(monkeypatch, start, end)
    first = chat_service.handle_message(db, "R5有货吗")

    rejected = chat_service.handle_message(db, "不是", session_id=first["session_id"])

    assert rejected["detected_intent"] == "checkout_rejected"
    assert rejected["next_actions"][0]["label"] == "重新选择设备"
    assert get_session_store().get(first["session_id"])["checkout_candidate"] == {}


def test_inventory_does_not_offer_checkout_when_quantity_is_insufficient(db, seeded):
    start = date.today() + timedelta(days=7)
    end = start + timedelta(days=1)

    result = chat_service._handle_inventory_query(
        db,
        {
            "devices": ["R5"],
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "quantity": 4,
        },
    )

    assert result.get("checkout_candidate") is None
    assert result.get("actions", []) == []
