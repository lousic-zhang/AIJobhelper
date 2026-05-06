from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ChatRequest(BaseModel):
    chat_id: str = "job-chat"
    message: str


class ChatResponse(BaseModel):
    reply: str
    handler: str
    tool: str | None = None
    debug: dict[str, Any] | None = None
