"""主动导购流程：逐轮反问、真实库存计价、免押说明与下单带入。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.knowledge_base import guide
from app.models.conversation import Conversation
from app.services import chat_service, sales_guide
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
    assert "下单页自行填写" in final["ai_response"]
    assert final["answer_source"] == "workflow"
    assert final["next_actions"][0]["label"] == "下单"
    assert final["next_actions"][0]["action"] == "prefill_order"
    payload = final["next_actions"][0]["payload"]
    assert payload["config_id"] == seeded["config"].id
    assert payload["start_date"] == start.isoformat()
    assert payload["end_date"] == end.isoformat()


def test_shipping_fields_extract_labeled_full_and_municipality_addresses():
    normal = sales_guide.extract_shipping_fields(
        "姓名：张三，电话：13800138000，地址：江西省南昌市西湖区丁公路北88号2栋301"
    )
    assert normal == {
        "receiver_name": "张三",
        "phone": "13800138000",
        "province": "江西省",
        "city": "南昌市",
        "district": "西湖区",
        "detail_address": "丁公路北88号2栋301",
    }

    municipality = sales_guide.extract_shipping_fields(
        "收货地址：北京市朝阳区望京街道88号3栋201"
    )
    assert municipality["province"] == "北京市"
    assert municipality["city"] == "北京市"
    assert municipality["district"] == "朝阳区"


def test_confirmed_device_and_dates_go_directly_to_deposit_then_prefill(
    db, seeded, monkeypatch
):
    monkeypatch.setattr(guide.llm, "llm_available", lambda: False)
    start = date.today() + timedelta(days=20)
    end = start + timedelta(days=2)

    first = chat_service.handle_message(
        db, f"我要租R5，{start.isoformat()}到{end.isoformat()}"
    )

    assert first["detected_intent"] == "guided_sales"
    assert "是否需要申请免押" in first["ai_response"]
    assert [action["label"] for action in first["next_actions"]] == [
        "需要免押",
        "不需要免押",
        "下单",
    ]
    assert "主要拍什么" not in first["ai_response"]

    final = chat_service.handle_message(
        db, "不需要免押", session_id=first["session_id"]
    )
    payload = final["next_actions"][0]["payload"]
    assert payload["camera_id"] == seeded["camera"].id
    assert payload["config_id"] == seeded["config"].id
    assert payload["start_date"] == start.isoformat()
    assert payload["end_date"] == end.isoformat()
    assert "shipping_address" not in payload
    assert "下单页自行填写" in final["ai_response"]


def test_compact_device_and_relative_dates_offer_checkout_without_llm(
    db, seeded, monkeypatch
):
    monkeypatch.setattr(guide.llm, "llm_available", lambda: False)

    first = chat_service.handle_message(db, "租R5明后天")

    assert first["detected_intent"] == "guided_sales"
    assert "是否需要申请免押" in first["ai_response"]
    checkout = next(
        action for action in first["next_actions"]
        if action["action"] == "prefill_order"
    )
    assert checkout["label"] == "下单"
    assert checkout["payload"]["camera_id"] == seeded["camera"].id
    assert checkout["payload"]["start_date"] == (
        date.today() + timedelta(days=1)
    ).isoformat()
    assert checkout["payload"]["end_date"] == (
        date.today() + timedelta(days=2)
    ).isoformat()

    confirmed = chat_service.handle_message(db, "对", session_id=first["session_id"])
    assert confirmed["detected_intent"] == "checkout_confirmed"
    assert confirmed["next_actions"][0]["label"] == "下单"


def test_shipping_address_is_prefilled_and_raw_pii_is_redacted_across_instances(
    db, seeded, monkeypatch
):
    monkeypatch.setattr(guide.llm, "llm_available", lambda: False)
    start = date.today() + timedelta(days=24)
    end = start + timedelta(days=2)
    message = (
        f"我要租R5，{start.isoformat()}到{end.isoformat()}，"
        "姓名：张三，电话：13800138000，地址：江西省南昌市西湖区丁公路北88号2栋301"
    )

    first = chat_service.handle_message(db, message)
    row = db.execute(
        select(Conversation).where(
            Conversation.session_id == first["session_id"],
            Conversation.round_number == 1,
        )
    ).scalars().one()
    assert "13800138000" not in row.user_message
    assert "丁公路" not in row.user_message
    assert "原文已脱敏" in row.user_message
    assert row.entities["sales_journey"]["shipping_address"]["receiver_name"] == "张三"

    get_session_store().delete(first["session_id"])
    final = chat_service.handle_message(
        db, "不需要免押", session_id=first["session_id"]
    )
    payload = final["next_actions"][0]["payload"]
    assert payload["shipping_address"] == {
        "receiver_name": "张三",
        "phone": "13800138000",
        "province": "江西省",
        "city": "南昌市",
        "district": "西湖区",
        "detail_address": "丁公路北88号2栋301",
    }
    assert "完整收货信息" in final["ai_response"]


def test_partial_shipping_fields_are_prefilled_without_guessing(db, seeded, monkeypatch):
    monkeypatch.setattr(guide.llm, "llm_available", lambda: False)
    start = date.today() + timedelta(days=28)
    end = start + timedelta(days=2)
    first = chat_service.handle_message(
        db,
        f"我要租R5，{start.isoformat()}到{end.isoformat()}，姓名：张三，电话：13800138000",
    )

    final = chat_service.handle_message(
        db, "不需要免押", session_id=first["session_id"]
    )
    shipping = final["next_actions"][0]["payload"]["shipping_address"]
    assert shipping == {"receiver_name": "张三", "phone": "13800138000"}
    assert "缺少的内容请在下单页自行补全" in final["ai_response"]


def test_shipping_pii_is_redacted_before_any_llm_call(db, monkeypatch):
    captured = []
    monkeypatch.setattr(guide.llm, "llm_available", lambda: True)

    def answer(messages, **kwargs):
        captured.append(messages)
        if kwargs.get("json_mode"):
            return '{"intent":"unknown","confidence":0.3,"entities":{}}'
        return "请在下单页核对并填写收货信息。"

    monkeypatch.setattr(guide.llm, "chat_completion", answer)
    chat_service.handle_message(
        db,
        "姓名：张三，电话：13800138000，地址：江西省南昌市西湖区丁公路北88号2栋301",
    )

    llm_input = str(captured)
    assert "13800138000" not in llm_input
    assert "丁公路" not in llm_input
    assert "原文已脱敏" in llm_input


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
    assert "已记下起租日" in result["ai_response"]
    assert "请告诉我归还日" in result["ai_response"]


def test_relative_dates_complete_waiting_sales_journey(db, seeded, monkeypatch):
    sid = _reach_date_step(db, monkeypatch)

    result = chat_service.handle_message(db, "明天租，后天还", session_id=sid)

    assert result["detected_intent"] == "guided_sales"
    assert result["answer_source"] == "workflow"
    assert "是否需要申请免押" in result["ai_response"]
    journey = get_session_store().get(sid)["sales_journey"]
    assert journey["start_date"] == (date.today() + timedelta(days=1)).isoformat()
    assert journey["end_date"] == (date.today() + timedelta(days=2)).isoformat()


def test_relative_dates_can_be_completed_across_two_rounds(db, seeded, monkeypatch):
    sid = _reach_date_step(db, monkeypatch)

    first = chat_service.handle_message(db, "明天租", session_id=sid)
    assert "已记下起租日" in first["ai_response"]
    assert "请告诉我归还日" in first["ai_response"]

    second = chat_service.handle_message(db, "后天还", session_id=sid)
    assert "是否需要申请免押" in second["ai_response"]


def test_duration_can_complete_a_known_start_date(db, seeded, monkeypatch):
    sid = _reach_date_step(db, monkeypatch)
    chat_service.handle_message(db, "明天租", session_id=sid)

    result = chat_service.handle_message(db, "租三天", session_id=sid)

    assert "是否需要申请免押" in result["ai_response"]
    journey = get_session_store().get(sid)["sales_journey"]
    assert journey["end_date"] == (date.today() + timedelta(days=3)).isoformat()


def test_slash_date_range_completes_waiting_sales_journey(db, seeded, monkeypatch):
    sid = _reach_date_step(db, monkeypatch)
    start = date.today() + timedelta(days=10)
    end = start + timedelta(days=2)

    result = chat_service.handle_message(
        db, f"{start.month}/{start.day}~{end.month}/{end.day}", session_id=sid
    )

    assert "是否需要申请免押" in result["ai_response"]
    journey = get_session_store().get(sid)["sales_journey"]
    assert journey["start_date"] == start.isoformat()
    assert journey["end_date"] == end.isoformat()


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
