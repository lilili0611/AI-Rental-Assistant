"""意图识别兜底规则测试。"""
from __future__ import annotations

from datetime import date

from app.config import settings
from app.intent import recognizer


def test_rule_recognizer_knows_real_catalog_ids(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "")

    result = recognizer.recognize("R10 九月一号到五号多少钱")

    year = date.today().year
    if date(year, 9, 1) < date.today():
        year += 1
    assert result.intent == "pricing_query"
    assert result.entities["devices"] == ["R10"]
    assert result.entities["start_date"] == f"{year}-09-01"
    assert result.entities["end_date"] == f"{year}-09-05"


def test_rule_recognizer_extracts_seed_catalog_names(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "")

    result = recognizer.recognize("XM5 9月1日到9月3日有货吗")

    year = date.today().year
    if date(year, 9, 1) < date.today():
        year += 1
    assert result.intent == "inventory_query"
    assert result.entities["devices"] == ["XM5"]
    assert result.entities["start_date"] == f"{year}-09-01"
    assert result.entities["end_date"] == f"{year}-09-03"
