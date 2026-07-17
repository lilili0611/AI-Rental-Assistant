"""本地客服 FAQ 解析与确定性检索。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Optional


_SOURCE_FILE = Path(__file__).with_name("真实客服问答.md")
_ENTRY_PATTERN = re.compile(
    r"\*\*(\d+)\.\s*问：(.*?)\*\*\s*\n答：(.*?)"
    r"(?=\n\*\*\d+\.\s*问：|\n###|\Z)",
    re.DOTALL,
)
_NON_CONTENT = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")


@dataclass(frozen=True)
class FAQEntry:
    entry_id: str
    question: str
    answer: str


@dataclass(frozen=True)
class KnowledgeMatch:
    entry: FAQEntry
    score: float


# 业务中具有明确指向的场景词。通用词（如“相机”“押金”“赔偿”）不单独
# 放入提示，避免相近政策之间误命中。
_HINTS: dict[str, tuple[str, ...]] = {
    "1": ("免押条件", "花呗免押", "免押方式"),
    "2": ("没有芝麻信用", "芝麻信用额度不够"),
    "3": ("开发票",),
    "4": ("线下自取", "自取地址"),
    "5": ("包含内存卡", "带内存卡"),
    "6": ("几块电池", "带电池", "充电器"),
    "7": ("镜头怎么选", "镜头选择", "不懂镜头参数"),
    "8": ("闪光灯", "三脚架"),
    "9": ("快门次数", "画质保障", "坏点", "霉斑"),
    "10": ("不会用相机", "教我用相机", "现场教学"),
    "11": ("后天要用", "什么时候下单"),
    "12": ("邮费谁出", "双向包邮", "包邮"),
    "13": ("包装安全", "运输途中摔坏", "快递摔坏"),
    "14": ("周末算", "节假日算", "自然日"),
    "15": ("指定时间送达", "准时送达"),
    "16": ("租期怎么计算", "签收次日", "收到寄回算几天"),
    "17": ("续租", "多用两天"),
    "18": ("提前还", "退租金"),
    "19": ("摔了相机", "摔了镜头", "相机摔坏", "镜头摔坏"),
    "20": ("意外保障服务", "意外保险", "保障值得买吗"),
    "21": ("镜头划痕也要赔", "保障服务镜头划痕"),
    "22": ("相机丢了", "设备丢了", "设备遗失"),
    "23": ("电池充不进电", "读卡器坏"),
    "24": ("下雨天进水", "雨中拍摄进水"),
    "25": ("归还怎么打包", "寄回怎么打包"),
    "26": ("照片要删", "格式化内存卡", "隐私照片"),
    "27": ("押金多久退", "退押金", "押金到账"),
    "28": ("收货发现划痕", "不是我弄的", "发货视频"),
    "29": ("川西", "风沙旅行"),
    "30": ("演唱会", "内场前排"),
    "31": ("年会", "公司活动拍摄"),
    "32": ("淘宝服装", "服装模特", "电商服装"),
    "33": ("机身划痕2mm", "2mm划痕"),
    "34": ("10mm裂痕", "镜头磕碰10mm"),
    "35": ("镜片5mm划痕", "5mm划痕"),
    "36": ("uv镜变形", "uv镜严重磨损"),
    "37": ("卡口变形",),
    "38": ("对焦失灵", "摔后不能对焦"),
    "39": ("相机进水", "进水全赔"),
    "40": ("镜片凹坑",),
    "41": ("申请理赔", "理赔流程"),
    "42": ("理赔证明", "理赔材料"),
    "43": ("理赔结果有异议", "理赔异议"),
    "44": ("维修期间租金", "维修占用费"),
    "45": ("首次拆修", "拆修10%"),
    "46": ("避免高额赔偿", "降低赔偿"),
    "47": ("都只赔500", "所有损坏500"),
    "48": ("镜头盖丢",),
    "49": ("相机包坏",),
    "50": ("自然老化", "正常老化"),
    "51": ("一周后发现划痕", "租期结束后发现"),
    "52": ("多个损坏部位", "多处损坏", "赔偿累计"),
}


def _normalize(text: str) -> str:
    return _NON_CONTENT.sub("", text.lower())


def _bigrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text} if text else set()
    return {text[index : index + 2] for index in range(len(text) - 1)}


@lru_cache(maxsize=1)
def load_entries() -> tuple[FAQEntry, ...]:
    source = _SOURCE_FILE.read_text(encoding="utf-8")
    entries = tuple(
        FAQEntry(entry_id=entry_id, question=question.strip(), answer=answer.strip())
        for entry_id, question, answer in _ENTRY_PATTERN.findall(source)
    )
    if len(entries) != 52:
        raise RuntimeError(f"客服知识库应包含 52 条，实际解析到 {len(entries)} 条")
    return entries


def _score(query: str, entry: FAQEntry) -> tuple[float, bool]:
    target = _normalize(entry.question)
    sequence = SequenceMatcher(None, query, target).ratio()
    query_pairs = _bigrams(query)
    target_pairs = _bigrams(target)
    overlap = len(query_pairs & target_pairs) / max(1, min(len(query_pairs), len(target_pairs)))
    score = sequence * 0.58 + overlap * 0.42

    strong_hint = False
    for hint in _HINTS.get(entry.entry_id, ()):
        normalized_hint = _normalize(hint)
        if normalized_hint and normalized_hint in query:
            strong_hint = True
            score = max(score, min(0.98, 0.82 + len(normalized_hint) * 0.015))

    if len(query) >= 4 and (query in target or target in query):
        score = max(score, 0.80)
    return score, strong_hint


def search(query: str) -> Optional[KnowledgeMatch]:
    """返回高置信度 FAQ；模糊或过短的问题交给后续业务/LLM 路由。"""
    normalized = _normalize(query)
    if len(normalized) < 2:
        return None

    ranked = []
    for entry in load_entries():
        score, strong_hint = _score(normalized, entry)
        ranked.append((score, strong_hint, entry))
    ranked.sort(key=lambda item: item[0], reverse=True)

    best_score, best_has_hint, best_entry = ranked[0]
    second_score = ranked[1][0]
    if best_score < 0.58:
        return None
    if not best_has_hint and best_score - second_score < 0.04:
        return None
    return KnowledgeMatch(entry=best_entry, score=best_score)
