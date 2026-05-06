from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import uuid4

import bcrypt
from fastapi import HTTPException, Request

from app.core.config import Settings
from app.core.session import SessionData, SessionStore
from app.models.user import UserDocument

try:
    from pymongo import ReturnDocument
except ImportError:  # pragma: no cover
    class ReturnDocument:
        AFTER = None


class AuthService:
    def __init__(self, database: Any, session_store: SessionStore, settings: Settings) -> None:
        self.collection = database["users"]
        self.session_store = session_store
        self.settings = settings

    def register(self, email: str, nickname: str, password: str, confirm_password: str) -> tuple[UserDocument, SessionData]:
        email = email.strip().lower()
        nickname = nickname.strip()
        self._validate_registration(email=email, nickname=nickname, password=password, confirm_password=confirm_password)
        if self.collection.find_one({"email": email}):
            raise ValueError("This email is already registered.")

        now = datetime.utcnow()
        document = {
            "_id": uuid4().hex,
            "email": email,
            "nickname": nickname,
            "password_hash": self._hash_password(password),
            "created_at": now,
            "updated_at": now,
            "last_login_at": now,
            "status": "active",
            "role": "user",
        }
        self.collection.insert_one(document)
        user = self._to_user(document)
        try:
            session = self.session_store.create_session(user_id=user.id, email=user.email)
        except Exception as exc:
            raise ValueError("Redis session is unavailable. Check REDIS_URL and Redis auth settings.") from exc
        return user, session

    def login(self, email: str, password: str) -> tuple[UserDocument, SessionData]:
        email = email.strip().lower()
        document = self.collection.find_one({"email": email})
        if not document:
            raise ValueError("Incorrect email or password.")

        user = self._to_user(document)
        if user.status != "active":
            raise ValueError("This account is not active.")
        if not self._verify_password(password, user.password_hash):
            raise ValueError("Incorrect email or password.")

        now = datetime.utcnow()
        self.collection.find_one_and_update(
            {"_id": user.id},
            {"$set": {"last_login_at": now, "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        refreshed = self.collection.find_one({"_id": user.id})
        user = self._to_user(refreshed)
        try:
            session = self.session_store.create_session(user_id=user.id, email=user.email)
        except Exception as exc:
            raise ValueError("Redis session is unavailable. Check REDIS_URL and Redis auth settings.") from exc
        return user, session

    def logout(self, request: Request) -> None:
        session_id = request.cookies.get(self.settings.session_cookie_name)
        self.session_store.delete_session(session_id)

    def get_current_user(self, request: Request, refresh: bool = True) -> UserDocument | None:
        session_id = request.cookies.get(self.settings.session_cookie_name)
        if not session_id:
            return None
        try:
            session = self.session_store.get_session(session_id)
        except Exception:
            return None
        if session is None:
            return None
        if refresh:
            try:
                session = self.session_store.refresh_session(session_id) or session
            except Exception:
                return None
        document = self.collection.find_one({"_id": session.user_id, "status": "active"})
        if not document:
            self.session_store.delete_session(session_id)
            return None
        return self._to_user(document)

    def require_api_user(self, request: Request) -> UserDocument:
        user = self.get_current_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="Please log in first.")
        return user

    def _validate_registration(self, email: str, nickname: str, password: str, confirm_password: str) -> None:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise ValueError("Invalid email format.")
        if len(nickname) < 2:
            raise ValueError("Nickname must be at least 2 characters.")
        if len(password) < 6:
            raise ValueError("Password must be at least 6 characters.")
        if password != confirm_password:
            raise ValueError("Passwords do not match.")

    def _hash_password(self, password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def _verify_password(self, password: str, password_hash: str) -> bool:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))

    def _to_user(self, document: dict[str, Any]) -> UserDocument:
        mapped = dict(document)
        mapped["_id"] = str(mapped["_id"])
        return UserDocument.model_validate(mapped)

