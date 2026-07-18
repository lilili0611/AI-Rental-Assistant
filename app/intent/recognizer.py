"""意图识别 (Spec 6.2)。

9 类意图: device_query / device_compare / inventory_query / pricing_query /
deposit_query / order_create / order_modify / order_cancel / logistics_query。

优先用 DeepSeek; 未配置 Key 或调用失败时降级到关键词规则。
同时抽取实体: 设备名/型号、日期区间、天数、数量等。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from app.integrations import llm

INTENTS = [
    "device_query",
    "device_compare",
    "inventory_query",
    "pricing_query",
    "deposit_query",
    "order_create",
    "order_modify",
    "order_cancel",
    "logistics_query",
    "unknown",
]

# 需要认证的意图 (Spec 6.3)
AUTH_REQUIRED = {"order_create", "order_modify", "order_cancel", "logistics_query"}
# 涉及金钱、即使高置信度也需二次确认 (Spec 6.2)
MONEY_SENSITIVE = {"order_create", "order_modify", "order_cancel"}


@dataclass
class IntentResult:
    intent: str
    confidence: float
    entities: dict = field(default_factory=dict)
    source: str = "rule"  # rule / llm


# ============ 关键词规则(降级用) ============
_RULES = [
    ("order_cancel", ["取消订单", "取消", "退订", "不租了"]),
    ("order_modify", ["改期", "延期", "修改订单", "改订单", "续租", "改数量"]),
    ("order_create", ["下单", "我要租", "预订", "预定", "租这个", "下订单", "要租"]),
    ("logistics_query", ["物流", "快递", "发货了吗", "到哪了", "运单", "签收"]),
    ("deposit_query", ["押金", "保证金", "定金"]),
    ("pricing_query", ["多少钱", "价格", "租金", "报价", "费用", "贵不贵", "几天多少"]),
    ("inventory_query", ["有货", "有没有", "库存", "还有吗", "能租吗", "可用", "余量"]),
    ("device_compare", ["对比", "比较", "哪个好", "区别", "和", "vs"]),
    ("device_query", ["有什么", "设备", "相机", "镜头", "型号", "介绍", "参数", "规格", "配置"]),
]


def _rule_intent(message: str) -> IntentResult:
    text = message.strip()
    for intent, keywords in _RULES:
        for kw in keywords:
            if kw in text:
                # device_compare 需要至少两个对比对象的弱信号
                if intent == "device_compare" and kw in ("和", "vs") and len(text) < 6:
                    continue
                # 明确关键词命中给较高置信度: 查询类可直接执行,
                # 金钱敏感意图(下单/改单/取消)仍由 chat_service 强制二次确认。
                return IntentResult(intent=intent, confidence=0.85, source="rule")
    return IntentResult(intent="unknown", confidence=0.3, source="rule")


# ============ 实体抽取 ============
_CAMERA_PATTERN = re.compile(
    r"(G7X2|G12|R10|POCKET\s*3|POCKET3|FLIP|XM5|A620|IXUS\s*110|IXUS110|"
    r"U300|U400|U1|R5C|R5|R6|R7|R8|A7M4|A7R5|A7S3|Z6|Z7|Z8|Z9|GFX|X-T\d|EOS\s*\w+|"
    r"[0-9]{2,3}-[0-9]{2,3}mm|[0-9]{2,3}mm)",
    re.IGNORECASE,
)
_DAYS_PATTERN = re.compile(r"(\d+|[一二三四五六七八九十]{1,3})\s*天")
_QTY_PATTERN = re.compile(r"(\d+)\s*(台|个|只)")
_DATE_PATTERN = re.compile(
    r"(?<!\d)(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}[日号]?|"
    r"\d{1,2}[-/.月]\d{1,2}[日号]?)(?!\d)"
)
_CN_NUM = "零一二三四五六七八九十"
_CN_MONTH_DAY = re.compile(
    r"([零一二三四五六七八九十\d]{1,3})月([零一二三四五六七八九十\d]{1,3})[号日]?"
)
_CN_RANGE_TAIL = re.compile(
    r"(?:到|至|~|-|—)\s*([零一二三四五六七八九十\d]{1,3})[号日]?"
)
_RELATIVE_DATE_PATTERN = re.compile(r"大后天|后天|明天|今天")
_RELATIVE_DATE_OFFSETS = {"今天": 0, "明天": 1, "后天": 2, "大后天": 3}
_END_DATE_CUE_PATTERN = re.compile(r"归还|还机|还回|还|结束|截止|到期|延期|延长|改期")


def extract_entities(message: str) -> dict:
    """从消息抽取设备、日期、天数、数量等实体。"""
    entities: dict = {}

    devices = _CAMERA_PATTERN.findall(message)
    if devices:
        # 去重保序
        seen = []
        for d in devices:
            d = d.upper().replace(" ", "")
            if d == "POCKET3":
                d = "POCKET3"
            if d not in seen:
                seen.append(d)
        entities["devices"] = seen

    duration_days = _extract_duration_days(message)
    if duration_days:
        entities["days"] = duration_days

    qty_m = _QTY_PATTERN.search(message)
    if qty_m:
        entities["quantity"] = int(qty_m.group(1))

    dates = _parse_dates(message)
    if dates:
        entities.update(dates)

    return entities


def _parse_dates(message: str) -> dict:
    """解析日期区间。支持相对日期、多种数字格式与日期+天数。"""
    relative_dates = _parse_relative_dates(message)
    if relative_dates:
        return relative_dates

    raw = _DATE_PATTERN.findall(message)
    has_explicit_or_numeric_format = bool(
        len(raw) >= 2
        or any(re.search(r"\d{4}|年|/|\.", token) for token in raw)
    )
    if raw and has_explicit_or_numeric_format:
        absolute_dates = _parse_absolute_dates(message, raw)
        if absolute_dates:
            return absolute_dates

    cn_dates = _parse_chinese_month_day(message)
    if cn_dates:
        return cn_dates

    return _parse_absolute_dates(message, raw) if raw else {}


def _single_date_result(value: date, message: str) -> dict:
    """单日期根据“还/归还/延期”等语义映射为归还日。"""
    key = "end_date" if _END_DATE_CUE_PATTERN.search(message) else "start_date"
    result = {key: value.isoformat()}
    duration_days = _extract_duration_days(message)
    if key == "start_date" and duration_days:
        result["end_date"] = (value + timedelta(days=duration_days - 1)).isoformat()
    return result


def _parse_relative_dates(message: str) -> dict:
    matches = list(_RELATIVE_DATE_PATTERN.finditer(message))
    if not matches:
        return {}
    today = date.today()
    values = [today + timedelta(days=_RELATIVE_DATE_OFFSETS[m.group(0)]) for m in matches]
    if len(values) >= 2:
        return {"start_date": values[0].isoformat(), "end_date": values[1].isoformat()}
    return _single_date_result(values[0], message)


def _parse_date_token(raw: str) -> tuple[Optional[date], bool]:
    normalized = (
        raw.replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .replace("号", "")
        .replace("/", "-")
        .replace(".", "-")
        .strip("- ")
    )
    parts = normalized.split("-")
    explicit_year = len(parts) == 3
    try:
        if explicit_year:
            year, month, day = map(int, parts)
            return date(year, month, day), True
        if len(parts) != 2:
            return None, False
        month, day = map(int, parts)
        return _future_date(date.today().year, month, day), False
    except ValueError:
        return None, explicit_year


def _parse_absolute_dates(message: str, raw: list[str]) -> dict:
    parsed = []
    for token in raw:
        value, explicit_year = _parse_date_token(token)
        if value:
            parsed.append((value, explicit_year))
    if len(parsed) >= 2:
        start, _ = parsed[0]
        end, end_has_year = parsed[1]
        if end < start and not end_has_year:
            try:
                end = date(end.year + 1, end.month, end.day)
            except ValueError:
                return {}
        return {"start_date": start.isoformat(), "end_date": end.isoformat()}
    if len(parsed) == 1:
        return _single_date_result(parsed[0][0], message)
    return {}


def _cn_to_int(raw: str) -> Optional[int]:
    """解析 1-31 范围内的中文/阿拉伯数字。"""
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    if raw == "十":
        return 10
    if "十" in raw:
        left, _, right = raw.partition("十")
        tens = 1 if not left else _CN_NUM.find(left)
        ones = 0 if not right else _CN_NUM.find(right)
        if tens < 0 or ones < 0:
            return None
        return tens * 10 + ones
    if len(raw) == 1 and raw in _CN_NUM:
        return _CN_NUM.find(raw)
    return None


def _extract_duration_days(message: str) -> Optional[int]:
    match = _DAYS_PATTERN.search(message)
    if not match:
        return None
    value = _cn_to_int(match.group(1))
    return value if value and value > 0 else None


def _future_date(year: int, month: int, day: int) -> Optional[date]:
    """无年份日期默认取今年；若已过去则取下一年。"""
    try:
        dt = date(year, month, day)
    except ValueError:
        return None
    if dt < date.today():
        try:
            dt = date(year + 1, month, day)
        except ValueError:
            return None
    return dt


def _parse_chinese_month_day(message: str) -> dict:
    """解析“九月一号到五号”“9月1日到9月3日”等中文口语日期。"""
    matches = list(_CN_MONTH_DAY.finditer(message))
    if not matches:
        return {}

    year = date.today().year
    parsed = []
    for m in matches:
        month = _cn_to_int(m.group(1))
        day = _cn_to_int(m.group(2))
        if not month or not day:
            continue
        dt = _future_date(year, month, day)
        if dt:
            parsed.append((dt, m))

    result: dict = {}
    if len(parsed) >= 2:
        result["start_date"] = parsed[0][0].isoformat()
        result["end_date"] = parsed[1][0].isoformat()
        return result

    if len(parsed) == 1:
        start, first_match = parsed[0]
        tail = _CN_RANGE_TAIL.search(message[first_match.end():])
        if tail:
            end_day = _cn_to_int(tail.group(1))
            if end_day:
                end = _future_date(start.year, start.month, end_day)
                if end and end < start:
                    end = _future_date(start.year + 1, start.month, end_day)
                if end:
                    result["start_date"] = start.isoformat()
                    result["end_date"] = end.isoformat()
        elif _extract_duration_days(message):
            days = _extract_duration_days(message)
            result["start_date"] = start.isoformat()
            result["end_date"] = (start + timedelta(days=days - 1)).isoformat()
        else:
            return _single_date_result(start, message)
    return result


# ============ LLM 识别 ============
_SYSTEM_PROMPT = """你是相机租赁平台的意图识别助手。请分析用户消息，识别意图并抽取实体。

可选意图(只能选一个):
- device_query: 查询有哪些设备/型号/参数/配置
- device_compare: 对比多个设备
- inventory_query: 查询某设备某日期是否有货/库存
- pricing_query: 询问租金/价格
- deposit_query: 询问押金
- order_create: 下单/预订
- order_modify: 改期/延期/修改订单
- order_cancel: 取消订单
- logistics_query: 查物流/快递
- unknown: 无法归类

请只返回 JSON，格式:
{"intent": "意图名", "confidence": 0.0到1.0的小数, "entities": {"devices": ["R5"], "days": 7, "quantity": 1, "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "order_id": "订单号"}}
规则:
- entities 中没有的字段一律省略，不要编造。
- 日期统一用 YYYY-MM-DD。今天是 {today}（{year} 年）。
- 用户没说年份时，按今天推断：用当年；若该日期已过去，则用下一年。
- "延期/改期到X"只给出一个目标日期时，把它放进 end_date，不要填 start_date。"""


_DATE_KEYS = {"start_date", "end_date"}


def _llm_intent(message: str) -> Optional[IntentResult]:
    try:
        today = date.today()
        # 用 replace 而非 format: prompt 内含 JSON 示例的 {} 大括号
        prompt = _SYSTEM_PROMPT.replace("{today}", today.isoformat()).replace(
            "{year}", str(today.year)
        )
        content = llm.chat_completion(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": message},
            ],
            json_mode=True,
        )
        data = llm.parse_json_response(content)
        if not data or "intent" not in data:
            return None
        intent = data["intent"]
        if intent not in INTENTS:
            intent = "unknown"
        confidence = float(data.get("confidence", 0.7))
        entities = data.get("entities", {}) or {}
        # 用规则补全 LLM 漏掉的实体; 但若 LLM 已给出任一日期,
        # 不再用规则补日期(避免把"延期到X"的目标日误塞成 start_date)。
        llm_has_date = any(entities.get(k) for k in _DATE_KEYS)
        rule_entities = extract_entities(message)
        for k, v in rule_entities.items():
            if k in _DATE_KEYS and llm_has_date:
                continue
            entities.setdefault(k, v)
        return IntentResult(
            intent=intent, confidence=confidence, entities=entities, source="llm"
        )
    except Exception:
        return None


def recognize(message: str) -> IntentResult:
    """识别意图: 优先 LLM, 失败降级规则。"""
    if llm.llm_available():
        result = _llm_intent(message)
        if result is not None:
            return result
    # 降级
    result = _rule_intent(message)
    result.entities = extract_entities(message)
    return result
