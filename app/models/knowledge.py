from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


KnowledgeBaseStatus = Literal["empty", "ingesting", "ready", "failed"]
KnowledgeMessageRole = Literal["user", "assistant", "system"]
KnowledgeFetchMode = Literal["http", "mcp"]
KnowledgeIngestStatus = Literal["running", "succeeded", "failed"]


class KnowledgeBaseCreateRequest(BaseModel):
    name: str


class KnowledgeBaseDocument(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    name: str
    role_scope: str = "job"
    status: KnowledgeBaseStatus = "empty"
    created_at: datetime
    updated_at: datetime
    last_ingested_at: datetime | None = None
    last_source_url: str = ""

    model_config = {"populate_by_name": True}


class KnowledgeMessageDocument(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    knowledge_base_id: str
    role: KnowledgeMessageRole
    content: str
    created_at: datetime

    model_config = {"populate_by_name": True}


class KnowledgeIngestJobDocument(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    knowledge_base_id: str
    source_url: str
    fetch_mode: KnowledgeFetchMode
    status: KnowledgeIngestStatus
    error_message: str = ""
    created_at: datetime
    finished_at: datetime | None = None

    model_config = {"populate_by_name": True}


class KnowledgeUrlIngestRequest(BaseModel):
    url: HttpUrl


class KnowledgeChatRequest(BaseModel):
    message: str


class KnowledgeSourceChunk(BaseModel):
    source_url: str
    title: str = ""
    content: str
    score: float = 0.0


class KnowledgeChatResponse(BaseModel):
    reply: str
    handler: str
    tool: str | None = None
    sources: list[KnowledgeSourceChunk] = Field(default_factory=list)
    debug: dict[str, object] | None = None

