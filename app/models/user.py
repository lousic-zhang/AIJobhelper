from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class UserDocument(BaseModel):
    id: str = Field(alias="_id")
    email: str
    nickname: str
    password_hash: str
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None
    status: str = "active"
    role: str = "user"

    model_config = {"populate_by_name": True}

