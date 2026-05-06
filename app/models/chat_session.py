from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ChatMessageRole = Literal["user", "assistant", "system"]


class ChatSessionDocument(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


class ChatSessionMessageDocument(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    chat_id: str
    role: ChatMessageRole
    content: str
    created_at: datetime

    model_config = {"populate_by_name": True}


class ChatSessionCreateRequest(BaseModel):
    title: str = ""


class ChatSessionRenameRequest(BaseModel):
    title: str
