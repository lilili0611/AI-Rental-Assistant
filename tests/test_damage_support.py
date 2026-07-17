"""损坏扣费标准图与定损安全边界测试。"""
from pathlib import Path

from app.knowledge_base import guide
from app.services import chat_service, damage_support


def test_damage_standard_asset_is_packaged_as_jpeg():
    asset = Path("app/static/damage-fee-standard.jpg")
    assert asset.exists()
    assert asset.read_bytes()[:3] == b"\xff\xd8\xff"


def test_general_damage_question_returns_standard_image(db, monkeypatch):
    monkeypatch.setattr(guide.llm, "llm_available", lambda: False)

    result = chat_service.handle_message(db, "相机磕碰磨损的赔付标准是什么？")

    assert result["detected_intent"] == "damage_policy"
    assert result["answer_source"] == "knowledge_base"
    assert "归还验收及客服确认为准" in result["ai_response"]
    assert result["next_actions"] == [
        {
            "type": "button",
            "label": "查看扣费标准图",
            "action": "open_url",
            "payload": {"url": "/static/damage-fee-standard.jpg"},
        }
    ]


def test_specific_scratch_question_still_returns_image_not_ai_assessment(db):
    result = chat_service.handle_message(db, "机身有2mm划痕怎么扣费？")
    assert result["detected_intent"] == "damage_policy"
    assert "最终损坏类型、尺寸和扣费金额" in result["ai_response"]
    assert result["next_actions"][0]["payload"]["url"] == damage_support.DAMAGE_STANDARD_URL


def test_dropped_camera_stops_use_and_returns_standard_image(db):
    result = chat_service.handle_message(db, "相机摔坏了怎么赔？")
    assert result["detected_intent"] == "damage_policy"
    assert result["ai_response"].startswith("请先关机并停止使用")
    assert result["next_actions"][0]["label"] == "查看扣费标准图"


def test_water_damage_does_not_claim_the_collision_chart_applies(db):
    result = chat_service.handle_message(db, "相机进水了怎么赔偿？")
    assert result["detected_intent"] == "usage_support"
    assert "停止使用" in result["ai_response"]
    assert result["next_actions"] == []
