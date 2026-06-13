"""DeepSeek LLM 客户端 (OpenAI 兼容协议)。

通过 httpx 直接调用 /chat/completions, 支持 JSON 模式输出。
未配置 API Key 时, llm_available() 返回 False, 上层自动降级到规则引擎。
"""
from __future__ import annotations

import json
from typing import List, Optional

import httpx

from app.config import settings


def llm_available() -> bool:
    return settings.llm_enabled


def chat_completion(
    messages: List[dict],
    *,
    json_mode: bool = False,
    temperature: float = 0.2,
    timeout: float = 30.0,
) -> str:
    """调用 DeepSeek chat completions, 返回回复文本。

    messages: [{"role": "system"/"user"/"assistant", "content": str}]
    json_mode: 要求模型返回合法 JSON。
    """
    if not settings.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置")

    payload = {
        "model": settings.deepseek_model,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


def parse_json_response(text: str) -> Optional[dict]:
    """从模型回复中尽力解析出 JSON 对象。"""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        # 尝试提取首个 { ... } 片段
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None
