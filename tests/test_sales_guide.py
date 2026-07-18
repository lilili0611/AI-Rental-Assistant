"""主动导购流程：逐轮反问、真实库存计价、免押说明与下单带入。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.knowledge_base import guide
from app.services import chat_service
from app.services.session_store import get_session_store


def _reach_date_step(db, monkeypatch) -> str:
    monkeypatch.setattr(guide.llm, "llm_available", lambda: False)
    first = chat_service.handle_message(db, "我想租相机，去旅行")
    sid = first["session_id"]
    chat_service.handle_message(db, "第一次用相机", session_id=sid)
    chat_service.handle_message(db, "轻便和画质均衡", session_id=sid)
    return sid


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


def test_side_question_while_waiting_dates_uses_llm_and_preserves_journey(
    db, seeded, monkeypatch
):
    sid = _reach_date_step(db, monkeypatch)
    before = dict(get_session_store().get(sid)["sales_journey"])
    captured = {}
    monkeypatch.setattr(guide.llm, "llm_available", lambda: True)

    def answer(messages, **kwargs):
        captured["messages"] = messages
        return "想拍复古人像，可优先选择带胶片模拟或色彩直出的轻便相机，再搭配大光圈镜头营造柔和背景虚化。"

    monkeypatch.setattr(guide.llm, "chat_completion", answer)

    result = chat_service.handle_message(
        db, "你可以给我推荐一个拍人很复古的相机吗", session_id=sid
    )

    assert result["detected_intent"] == "guided_sales_side_question"
    assert result["answer_source"] == "llm"
    assert result["ai_response"].startswith(f"{guide.AI_LABEL}\n")
    assert "不继续索要起租日或归还日" in captured["messages"][0]["content"]
    assert "公开相机型号" in captured["messages"][0]["content"]
    assert [action["label"] for action in result["next_actions"]] == [
        "继续填写租期",
        "重新选择设备",
    ]
    journey = get_session_store().get(sid)["sales_journey"]
    assert journey["paused"] is True
    assert journey["config_id"] == before["config_id"] == seeded["config"].id


def test_continue_dates_resumes_paused_journey(db, seeded, monkeypatch):
    sid = _reach_date_step(db, monkeypatch)
    monkeypatch.setattr(guide.llm, "llm_available", lambda: True)
    monkeypatch.setattr(
        guide.llm,
        "chat_completion",
        lambda *args, **kwargs: "可以选择轻便机身搭配大光圈镜头。",
    )
    chat_service.handle_message(db, "还有什么复古人像拍摄技巧吗？", session_id=sid)

    resumed = chat_service.handle_message(db, "继续填写租期", session_id=sid)

    assert resumed["detected_intent"] == "guided_sales"
    assert "起租日和归还日" in resumed["ai_response"]
    journey = get_session_store().get(sid)["sales_journey"]
    assert journey.get("paused") is None
    assert journey["config_id"] == seeded["config"].id


def test_restart_selection_clears_paused_journey(db, seeded, monkeypatch):
    sid = _reach_date_step(db, monkeypatch)
    monkeypatch.setattr(guide.llm, "llm_available", lambda: True)
    monkeypatch.setattr(
        guide.llm,
        "chat_completion",
        lambda *args, **kwargs: "可以选择轻便机身搭配大光圈镜头。",
    )
    chat_service.handle_message(db, "还有什么复古人像拍摄技巧吗？", session_id=sid)

    restarted = chat_service.handle_message(db, "重新选择设备", session_id=sid)

    assert restarted["detected_intent"] == "guided_sales"
    assert "主要拍什么" in restarted["ai_response"]
    journey = get_session_store().get(sid)["sales_journey"]
    assert "config_id" not in journey
    assert "recommended" not in journey


def test_faq_side_question_keeps_journey_and_does_not_call_llm(
    db, seeded, monkeypatch
):
    sid = _reach_date_step(db, monkeypatch)
    monkeypatch.setattr(guide.llm, "llm_available", lambda: True)
    monkeypatch.setattr(
        guide.llm,
        "chat_completion",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("FAQ 命中不应调用 LLM")
        ),
    )

    result = chat_service.handle_message(db, "可以开发票吗？", session_id=sid)

    assert result["detected_intent"] == "knowledge_qa"
    assert result["answer_source"] == "knowledge_base"
    assert result["ai_response"] == "目前不支持"
    assert len(result["next_actions"]) == 2
    assert get_session_store().get(sid)["sales_journey"]["paused"] is True


def test_partial_date_answer_does_not_trigger_llm(db, seeded, monkeypatch):
    sid = _reach_date_step(db, monkeypatch)
    monkeypatch.setattr(guide.llm, "llm_available", lambda: True)
    monkeypatch.setattr(
        guide.llm,
        "chat_completion",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("日期回答不应调用 LLM")),
    )

    result = chat_service.handle_message(db, "7月20日开始", session_id=sid)

    assert result["detected_intent"] == "guided_sales"
    assert result["answer_source"] == "workflow"
    assert "起租日和归还日" in result["ai_response"]


def test_paused_journey_restores_from_database(db, seeded, monkeypatch):
    sid = _reach_date_step(db, monkeypatch)
    monkeypatch.setattr(guide.llm, "llm_available", lambda: True)
    monkeypatch.setattr(
        guide.llm,
        "chat_completion",
        lambda *args, **kwargs: "可以选择轻便机身搭配大光圈镜头。",
    )
    chat_service.handle_message(db, "还有什么复古人像拍摄技巧吗？", session_id=sid)
    get_session_store().delete(sid)

    restored = chat_service.handle_message(db, "继续填写租期", session_id=sid)

    assert restored["detected_intent"] == "guided_sales"
    assert "起租日和归还日" in restored["ai_response"]
    assert (
        get_session_store().get(sid)["sales_journey"]["config_id"]
        == seeded["config"].id
    )


@pytest.mark.parametrize("wording", ("拍人", "拍妹子", "人物照", "复古人像"))
def test_portrait_synonyms_are_recognized_before_daily_scene(db, seeded, wording):
    result = chat_service.handle_message(db, f"给我推荐{wording}相机")

    assert result["detected_intent"] == "guided_sales"
    assert "主要拍人像写真" in result["ai_response"]
