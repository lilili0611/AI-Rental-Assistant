"""对话 schema (Spec 4.4)。"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class ChatAction(BaseModel):
    type: str
    label: str
    action: str
    payload: Optional[dict] = None


class ChatResponse(BaseModel):
    session_id: str
    round: int
    detected_intent: str
    confidence: float
    ai_response: str
    answer_source: Literal[
        "knowledge_base", "business_data", "workflow", "llm", "customer_service"
    ] = "business_data"
    next_actions: List[ChatAction] = Field(default_factory=list)
    requires_auth: bool = False
