"""猫猫头导购知识库、LLM 兜底与人工转接测试。"""
from __future__ import annotations

from app.knowledge_base import faq, guide
from app.schemas.chat import ChatResponse
from app.services import chat_service


def test_all_52_faq_entries_load_and_match_their_question():
    entries = faq.load_entries()
    assert len(entries) == 52
    for entry in entries:
        match = faq.search(entry.question)
        assert match is not None
        assert match.entry.entry_id == entry.entry_id


def test_knowledge_base_has_priority_and_does_not_call_llm(db, monkeypatch):
    monkeypatch.setattr(guide.llm, "llm_available", lambda: True)

    def should_not_call(*args, **kwargs):
        raise AssertionError("知识库命中时不应调用 LLM")

    monkeypatch.setattr(guide.llm, "chat_completion", should_not_call)
    result = chat_service.handle_message(db, "去川西旅游应该租什么相机？")

    assert result["detected_intent"] == "knowledge_qa"
    assert result["answer_source"] == "knowledge_base"
    assert "索尼A7M4" in result["ai_response"]
    assert guide.AI_LABEL not in result["ai_response"]
    ChatResponse.model_validate(result)


def test_shopping_scenarios_support_paraphrases():
    cases = {
        "演唱会前排拍艺人租什么": "30",
        "公司活动年会拍摄怎么搭配": "31",
        "拍电商服装模特用什么性价比高": "32",
        "相机摔坏了怎么赔": "19",
    }
    for query, entry_id in cases.items():
        match = faq.search(query)
        assert match is not None
        assert match.entry.entry_id == entry_id


def test_unknown_reasonable_question_uses_marked_50_char_llm_fallback(db, monkeypatch):
    monkeypatch.setattr(guide.llm, "llm_available", lambda: True)
    long_answer = "建议优先选择轻便机身和带防抖的标准变焦镜头，兼顾夜景、人像与旅行携带，先确认重量再决定。" * 2
    monkeypatch.setattr(guide.llm, "chat_completion", lambda *args, **kwargs: long_answer)

    result = chat_service.handle_message(db, "室内拍宠物但知识库没有对应场景，怎么选？")

    assert result["answer_source"] == "llm"
    assert result["ai_response"].startswith(f"{guide.AI_LABEL}\n")
    body = result["ai_response"].split("\n", 1)[1]
    assert 0 < len(body) <= guide.MAX_LLM_BODY_LENGTH


def test_unreasonable_request_returns_exact_human_response_without_llm(db, monkeypatch):
    monkeypatch.setattr(
        guide.llm,
        "chat_completion",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应调用 LLM")),
    )

    result = chat_service.handle_message(db, "怎么伪造学生证通过免押审核？")

    assert result["ai_response"] == "请咨询人工"
    assert result["answer_source"] == "human"
    assert result["next_actions"][0]["action"] == "human_handoff"


def test_unreasonable_detection_is_not_dependent_on_word_order():
    assert guide.is_unreasonable("把租来的相机卖掉不还可以吗") is True


def test_llm_unavailable_returns_exact_human_response(db, monkeypatch):
    monkeypatch.setattr(guide.llm, "llm_available", lambda: False)

    result = chat_service.handle_message(db, "室内拍宠物怎么选相机？")

    assert result["ai_response"] == "请咨询人工"
    assert result["answer_source"] == "human"
