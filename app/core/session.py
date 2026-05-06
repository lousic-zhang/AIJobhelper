from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.config import Settings

try:
    import redis
except ImportError:  # pragma: no cover - optional dependency fallback
    redis = None


@dataclass
class SessionData:
    session_id: str
    user_id: str
    email: str
    created_at: str
    last_seen_at: str


class SessionStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = self._build_client()

    def _build_client(self) -> Any:
        if redis is None:
            raise RuntimeError("未安装 redis Python SDK，请安装 redis 依赖后再启用登录功能。")
        return redis.Redis.from_url(self.settings.redis_url, decode_responses=True)

    def create_session(self, user_id: str, email: str) -> SessionData:
        session_id = uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        payload = SessionData(
            session_id=session_id,
            user_id=user_id,
            email=email,
            created_at=now,
            last_seen_at=now,
        )
        self._client.setex(
            self._key(session_id),
            self.settings.session_ttl_seconds,
            json.dumps(payload.__dict__),
        )
        return payload

    def get_session(self, session_id: str | None) -> SessionData | None:
        if not session_id:
            return None
        data = self._client.get(self._key(session_id))
        if not data:
            return None
        payload = json.loads(data)
        return SessionData(**payload)

    def refresh_session(self, session_id: str) -> SessionData | None:
        session = self.get_session(session_id)
        if session is None:
            return None
        session.last_seen_at = datetime.now(timezone.utc).isoformat()
        self._client.setex(
            self._key(session_id),
            self.settings.session_ttl_seconds,
            json.dumps(session.__dict__),
        )
        return session

    def delete_session(self, session_id: str | None) -> None:
        if not session_id:
            return
        self._client.delete(self._key(session_id))

    def _key(self, session_id: str) -> str:
        return f"session:{session_id}"

