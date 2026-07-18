"""意图识别兜底规则测试。"""
from __future__ import annotations

from datetime import date, timedelta

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


def test_rule_recognizer_extracts_relative_rental_range(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "")

    result = recognizer.recognize("明天租，后天还")

    assert result.entities["start_date"] == (date.today() + timedelta(days=1)).isoformat()
    assert result.entities["end_date"] == (date.today() + timedelta(days=2)).isoformat()


def test_relative_single_date_uses_rental_or_return_role():
    assert recognizer.extract_entities("明天租")["start_date"] == (
        date.today() + timedelta(days=1)
    ).isoformat()
    assert recognizer.extract_entities("后天还")["end_date"] == (
        date.today() + timedelta(days=2)
    ).isoformat()


def test_chinese_single_date_uses_return_role():
    target = date.today() + timedelta(days=12)

    result = recognizer.extract_entities(f"{target.month}月{target.day}日归还")

    assert result == {"end_date": target.isoformat()}


def test_relative_date_and_chinese_duration_build_inclusive_range():
    result = recognizer.extract_entities("明天开始租三天")

    assert result["days"] == 3
    assert result["start_date"] == (date.today() + timedelta(days=1)).isoformat()
    assert result["end_date"] == (date.today() + timedelta(days=3)).isoformat()


def test_numeric_date_range_accepts_slash_dot_and_full_year_formats():
    start = date.today() + timedelta(days=10)
    end = start + timedelta(days=3)
    samples = (
        f"{start.month}/{start.day}~{end.month}/{end.day}",
        f"{start.month}.{start.day}-{end.month}.{end.day}",
        f"{start.year}-{start.month}-{start.day}到{end.year}-{end.month}-{end.day}",
    )

    for sample in samples:
        result = recognizer.extract_entities(sample)
        assert result["start_date"] == start.isoformat(), sample
        assert result["end_date"] == end.isoformat(), sample


def test_numeric_range_rolls_unlabeled_end_into_next_year():
    today = date.today()
    start = date(today.year, 12, 30)
    if start < today:
        start = date(today.year + 1, 12, 30)
    end = date(start.year + 1, 1, 2)

    result = recognizer.extract_entities("12/30~1/2")

    assert result["start_date"] == start.isoformat()
    assert result["end_date"] == end.isoformat()


def test_invalid_numeric_date_is_ignored():
    result = recognizer.extract_entities("2/30开始租")

    assert "start_date" not in result
    assert "end_date" not in result
