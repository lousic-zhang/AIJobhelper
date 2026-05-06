from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ApplicationStatus = Literal[
    "applied",
    "written_test",
    "interview",
    "hr_interview",
    "offer",
    "rejected",
    "closed",
]


class ApplicationCreateRequest(BaseModel):
    company: str
    position: str
    channel: str = "unknown"
    status: ApplicationStatus = "applied"
    delivery_time: datetime | None = None
    deadline: datetime | None = None
    note: str = ""


class ApplicationStatusUpdateRequest(BaseModel):
    status: ApplicationStatus
    note: str = ""


class ApplicationListItem(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    company: str
    position: str
    channel: str
    status: ApplicationStatus
    delivery_time: datetime | None = None
    deadline: datetime | None = None
    note: str = ""
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}

