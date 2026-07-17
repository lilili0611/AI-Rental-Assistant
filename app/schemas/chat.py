"""对话 schema (Spec 4.4)。"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class ChatAction(BaseModel):
    type: str
    label: str
    action: str


class ChatResponse(BaseModel):
    session_id: str
    round: int
    detected_intent: str
    confidence: float
    ai_response: str
    answer_source: Literal["knowledge_base", "business_data", "llm", "human"] = "business_data"
    next_actions: List[ChatAction] = []
    requires_auth: bool = False
