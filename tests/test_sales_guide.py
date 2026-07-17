"""主动导购流程：逐轮反问、真实库存计价、免押说明与下单带入。"""
from __future__ import annotations

from datetime import date, timedelta

from app.knowledge_base import guide
from app.services import chat_service
from app.services.session_store import get_session_store


def test_guided_sales_reaches_deposit_and_prefill(db, seeded, monkeypatch):
    monkeypatch.setattr(guide.llm, "llm_available", lambda: False)

    first = chat_service.handle_message(db, "我想租相机，去旅行")
    assert first["answer_source"] == "workflow"
    assert "第一次用相机" in first["ai_response"]
    sid = first["session_id"]

    second = chat_service.handle_message(db, "第一次用相机", session_id=sid)
    assert "更看重" in second["ai_response"]

    third = chat_service.handle_message(db, "轻便和画质均衡", session_id=sid)
    assert "我更推荐" in third["ai_response"]
    assert seeded["config"].config_name in third["ai_response"]
    assert "哪天开始" in third["ai_response"]

    start = date.today() + timedelta(days=10)
    end = start + timedelta(days=2)
    fourth = chat_service.handle_message(
        db,
        f"{start.isoformat()}到{end.isoformat()}",
        session_id=sid,
    )
    assert "是否需要申请免押" in fourth["ai_response"]
    assert "租3天" in fourth["ai_response"]

    final = chat_service.handle_message(db, "需要免押", session_id=sid)
    assert "免押方式（3选1）" in final["ai_response"]
    assert final["answer_source"] == "workflow"
    assert final["next_actions"][0]["action"] == "prefill_order"
    payload = final["next_actions"][0]["payload"]
    assert payload["config_id"] == seeded["config"].id
    assert payload["start_date"] == start.isoformat()
    assert payload["end_date"] == end.isoformat()


def test_guided_sales_restores_progress_from_database(db, seeded, monkeypatch):
    monkeypatch.setattr(guide.llm, "llm_available", lambda: False)
    first = chat_service.handle_message(db, "去旅行想租相机")
    sid = first["session_id"]

    # 模拟 Vercel 请求落到另一实例：进程内会话丢失，只剩数据库记录。
    get_session_store().delete(sid)
    restored = chat_service.handle_message(db, "第一次用相机", session_id=sid)

    assert restored["round"] == 2
    assert restored["answer_source"] == "workflow"
    assert "更看重" in restored["ai_response"]


def test_guide_asks_only_one_missing_dimension_each_turn(db, seeded, monkeypatch):
    monkeypatch.setattr(guide.llm, "llm_available", lambda: False)

    result = chat_service.handle_message(db, "帮我选相机")

    assert result["ai_response"].count("？") == 1
    assert "主要拍什么" in result["ai_response"]


def test_natural_travel_rental_wording_starts_guided_sales(db, seeded, monkeypatch):
    monkeypatch.setattr(guide.llm, "llm_available", lambda: False)

    result = chat_service.handle_message(db, "我想去旅行租相机")

    assert result["detected_intent"] == "guided_sales"
    assert result["answer_source"] == "workflow"
    assert "第一次用相机" in result["ai_response"]


def test_new_recommendation_does_not_reuse_completed_journey(db, seeded, monkeypatch):
    monkeypatch.setattr(guide.llm, "llm_available", lambda: False)
    store = get_session_store()
    first = chat_service.handle_message(db, "我想去旅行租相机")
    sid = first["session_id"]
    session = store.get(sid)
    session["sales_journey"].update(
        {
            "active": False,
            "scene": "travel",
            "experience": "beginner",
            "priority": "balanced",
            "camera_id": seeded["camera"].id,
            "config_id": seeded["config"].id,
            "start_date": (date.today() + timedelta(days=10)).isoformat(),
            "end_date": (date.today() + timedelta(days=12)).isoformat(),
            "deposit_choice": True,
        }
    )
    store.save(sid, session)

    result = chat_service.handle_message(db, "再给我推荐一台相机", session_id=sid)

    assert "主要拍什么" in result["ai_response"]
    assert not store.get(sid)["sales_journey"].get("config_id")
