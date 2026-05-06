from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.models.chat_session import (
    ChatSessionDocument,
    ChatSessionMessageDocument,
)


class ChatSessionService:
    def __init__(self, database) -> None:
        self.sessions = database["chat_sessions"]
        self.messages = database["chat_session_messages"]

    def create_session(self, user_id: str, title: str = "") -> ChatSessionDocument:
        now = datetime.now(UTC)
        title = (title or "").strip() or "New chat"
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
        }
        self.sessions.insert_one(document)
        return ChatSessionDocument.model_validate(document)

    def list_sessions(self, user_id: str) -> list[ChatSessionDocument]:
        rows = self.sessions.find({"user_id": user_id}).sort("updated_at", -1)
        return [ChatSessionDocument.model_validate(row) for row in rows]

    def get_session(self, user_id: str, chat_id: str) -> ChatSessionDocument | None:
        row = self.sessions.find_one({"_id": chat_id, "user_id": user_id})
        if not row:
            return None
        return ChatSessionDocument.model_validate(row)

    def require_session(self, user_id: str, chat_id: str) -> ChatSessionDocument:
        session = self.get_session(user_id, chat_id)
        if session is None:
            raise ValueError("Chat session not found.")
        return session

    def ensure_default_session(self, user_id: str, chat_id: str, title: str = "New chat") -> ChatSessionDocument:
        session = self.get_session(user_id, chat_id)
        if session is not None:
            return session
        now = datetime.now(UTC)
        document = {
            "_id": chat_id,
            "user_id": user_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
        }
        self.sessions.insert_one(document)
        return ChatSessionDocument.model_validate(document)

    def list_messages(self, user_id: str, chat_id: str, limit: int = 100) -> list[ChatSessionMessageDocument]:
        rows = self.messages.find({"user_id": user_id, "chat_id": chat_id}).sort("created_at", 1)
        documents = [ChatSessionMessageDocument.model_validate(row) for row in rows]
        if limit > 0:
            return documents[-limit:]
        return documents

    def rename_session(self, user_id: str, chat_id: str, title: str) -> ChatSessionDocument:
        session = self.require_session(user_id, chat_id)
        cleaned = " ".join((title or "").strip().split()) or session.title
        updated = self.sessions.find_one_and_update(
            {"_id": chat_id, "user_id": user_id},
            {"$set": {"title": cleaned[:64], "updated_at": datetime.now(UTC)}},
        )
        if not updated:
            raise ValueError("Chat session not found.")
        return ChatSessionDocument.model_validate(updated)

    def delete_session(self, user_id: str, chat_id: str) -> None:
        self.require_session(user_id, chat_id)
        self.sessions.delete_one({"_id": chat_id, "user_id": user_id})
        self.messages.delete_many({"user_id": user_id, "chat_id": chat_id})

    def append_message(self, user_id: str, chat_id: str, role: str, content: str) -> ChatSessionMessageDocument:
        now = datetime.now(UTC)
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "chat_id": chat_id,
            "role": role,
            "content": content,
            "created_at": now,
        }
        self.messages.insert_one(document)
        self.sessions.find_one_and_update(
            {"_id": chat_id, "user_id": user_id},
            {"$set": {"updated_at": now}},
        )
        return ChatSessionMessageDocument.model_validate(document)

    def append_exchange(self, user_id: str, chat_id: str, user_message: str, assistant_message: str) -> None:
        self.append_message(user_id, chat_id, "user", user_message)
        self.append_message(user_id, chat_id, "assistant", assistant_message)

    def maybe_update_title_from_message(self, user_id: str, chat_id: str, message: str) -> None:
        session = self.get_session(user_id, chat_id)
        if session is None:
            return
        if session.title != "New chat":
            return
        title = self._title_from_message(message)
        self.sessions.find_one_and_update(
            {"_id": chat_id, "user_id": user_id},
            {"$set": {"title": title, "updated_at": datetime.now(UTC)}},
        )

    def _title_from_message(self, message: str) -> str:
        text = " ".join((message or "").strip().split())
        if not text:
            return "New chat"
        return text[:32].rstrip(" ,，。.!！？?;；:")
