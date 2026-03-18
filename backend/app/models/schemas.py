from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import uuid


def gen_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.utcnow().isoformat()


# --- Conversation ---

class ConversationCreate(BaseModel):
    title: Optional[str] = "New Chat"


class ConversationResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


# --- Message ---

class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str  # "user" | "assistant"
    content: str
    created_at: str


# --- Chat ---

class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    provider: Optional[str] = "openai"
    model: Optional[str] = "gpt-4o-mini"
    api_key: Optional[str] = None
    api_base: Optional[str] = None


# --- Settings ---

class ProviderSettings(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    api_key: str = ""
    api_base: Optional[str] = None


class AppSettings(BaseModel):
    providers: List[ProviderSettings] = Field(default_factory=lambda: [ProviderSettings()])
    active_provider_index: int = 0


import json


def sse_json(step: str, data) -> str:
    payload = {"step": step, "data": data}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
