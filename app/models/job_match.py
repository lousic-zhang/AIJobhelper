from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


JobMatchTaskStatus = Literal["queued", "running", "succeeded", "failed"]


class JobMatchImportRequest(BaseModel):
    urls: list[HttpUrl] = Field(min_length=1)


class JobMatchTaskDocument(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    source_url: str
    source_urls: list[str] = Field(default_factory=list)
    source_domain: str
    status: JobMatchTaskStatus
    current_stage: str = "queued"
    progress_message: str = ""
    error_message: str = ""
    total_pages_found: int = 0
    total_jobs_found: int = 0
    total_jobs_matched: int = 0
    created_at: datetime
    updated_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = {"populate_by_name": True}


class JobMatchResultDocument(BaseModel):
    id: str = Field(alias="_id")
    task_id: str
    user_id: str
    title: str
    company: str
    location: str = ""
    source_url: str
    summary_text: str = ""
    jd_text: str = ""
    keywords: list[str] = Field(default_factory=list)
    match_score: int
    match_rank: int
    match_reason_short: str = ""
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    created_at: datetime

    model_config = {"populate_by_name": True}


class JobMatchTaskDetailResponse(BaseModel):
    task: JobMatchTaskDocument
    results: list[JobMatchResultDocument] = Field(default_factory=list)
