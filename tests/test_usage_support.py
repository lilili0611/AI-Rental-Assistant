"""设备指南与安全故障排查测试。"""
from app.services import usage_support


def test_device_question_returns_official_guide_action():
    result = usage_support.answer("R10 怎么设置参数拍人像？")
    assert result is not None
    assert "快速上手" in result["text"]
    assert result["actions"][0]["action"] == "open_url"
    assert result["actions"][0]["payload"]["url"].startswith("https://")


def test_basic_failure_is_safe_and_non_destructive():
    result = usage_support.answer("相机存储卡错误怎么办？")
    assert "不要直接格式化" in result["text"]


def test_dangerous_failure_stops_use_and_points_to_customer_service():
    result = usage_support.answer("相机进水了还能开机吗？")
    assert result["customer_service"] is True
    assert "停止使用" in result["text"]
    assert "请咨询客服" in result["text"]
    assert result["actions"] == []
