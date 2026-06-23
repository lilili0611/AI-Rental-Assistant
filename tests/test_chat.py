"""聊天服务关键路径测试。"""
from __future__ import annotations

from app.config import settings
from app.services import chat_service


def test_device_query_for_config_uses_tier_prices(db, seeded, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "")

    result = chat_service.handle_message(db, "R5 有什么配置")

    assert result["detected_intent"] == "device_query"
    assert "R5 + 16-35mm" in result["ai_response"]
    assert "两天" in result["ai_response"]
    assert "三天" in result["ai_response"]
    assert "续租" in result["ai_response"]
