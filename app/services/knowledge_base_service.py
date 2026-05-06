from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from app.models.knowledge import (
    KnowledgeBaseDocument,
    KnowledgeBaseStatus,
    KnowledgeFetchMode,
    KnowledgeIngestJobDocument,
    KnowledgeIngestStatus,
    KnowledgeMessageDocument,
    KnowledgeMessageRole,
)


class KnowledgeBaseService:
    def __init__(self, database: Any) -> None:
        self.base_collection = database["knowledge_bases"]
        self.message_collection = database["knowledge_chat_messages"]
        self.ingest_collection = database["knowledge_ingest_jobs"]

    def create_base(self, user_id: str, name: str) -> KnowledgeBaseDocument:
        normalized = name.strip()
        if len(normalized) < 2:
            raise ValueError("知识库名称至少需要 2 个字符。")
        if self.base_collection.find_one({"user_id": user_id, "name": normalized}):
            raise ValueError("已存在同名知识库，请换一个名称。")

        now = datetime.utcnow()
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "name": normalized,
            "role_scope": "job",
            "status": "empty",
            "created_at": now,
            "updated_at": now,
            "last_ingested_at": None,
            "last_source_url": "",
        }
        self.base_collection.insert_one(document)
        return self._to_base(document)

    def list_bases(self, user_id: str) -> list[KnowledgeBaseDocument]:
        documents = self.base_collection.find({"user_id": user_id}).sort("updated_at", -1)
        return [self._to_base(document) for document in documents]

    def get_base(self, user_id: str, knowledge_base_id: str) -> KnowledgeBaseDocument | None:
        document = self.base_collection.find_one({"_id": knowledge_base_id, "user_id": user_id})
        if not document:
            return None
        return self._to_base(document)

    def require_base(self, user_id: str, knowledge_base_id: str) -> KnowledgeBaseDocument:
        knowledge_base = self.get_base(user_id, knowledge_base_id)
        if knowledge_base is None:
            raise ValueError("知识库不存在，或你没有访问权限。")
        return knowledge_base

    def update_base_status(
        self,
        *,
        user_id: str,
        knowledge_base_id: str,
        status: KnowledgeBaseStatus,
        last_source_url: str | None = None,
        last_ingested_at: datetime | None = None,
    ) -> KnowledgeBaseDocument:
        base = self.require_base(user_id, knowledge_base_id)
        patch: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.utcnow(),
        }
        if last_source_url is not None:
            patch["last_source_url"] = last_source_url
        if last_ingested_at is not None:
            patch["last_ingested_at"] = last_ingested_at
        document = self.base_collection.find_one_and_update(
            {"_id": base.id, "user_id": user_id},
            {"$set": patch},
        )
        if document is None:
            document = self.base_collection.find_one({"_id": base.id, "user_id": user_id})
        return self._to_base(document)

    def create_ingest_job(
        self,
        *,
        user_id: str,
        knowledge_base_id: str,
        source_url: str,
        fetch_mode: KnowledgeFetchMode,
    ) -> KnowledgeIngestJobDocument:
        now = datetime.utcnow()
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "knowledge_base_id": knowledge_base_id,
            "source_url": source_url,
            "fetch_mode": fetch_mode,
            "status": "running",
            "error_message": "",
            "created_at": now,
            "finished_at": None,
        }
        self.ingest_collection.insert_one(document)
        return self._to_ingest_job(document)

    def finish_ingest_job(
        self,
        *,
        user_id: str,
        job_id: str,
        status: KnowledgeIngestStatus,
        error_message: str = "",
        fetch_mode: KnowledgeFetchMode | None = None,
    ) -> KnowledgeIngestJobDocument:
        patch = {
            "status": status,
            "error_message": error_message,
            "finished_at": datetime.utcnow(),
        }
        if fetch_mode is not None:
            patch["fetch_mode"] = fetch_mode
        document = self.ingest_collection.find_one_and_update(
            {"_id": job_id, "user_id": user_id},
            {"$set": patch},
        )
        if document is None:
            document = self.ingest_collection.find_one({"_id": job_id, "user_id": user_id})
        return self._to_ingest_job(document)

    def list_messages(self, user_id: str, knowledge_base_id: str, limit: int = 50) -> list[KnowledgeMessageDocument]:
        documents = self.message_collection.find(
            {
                "user_id": user_id,
                "knowledge_base_id": knowledge_base_id,
            }
        ).sort("created_at", 1)
        items = [self._to_message(document) for document in documents]
        if limit > 0:
            return items[-limit:]
        return items

    def append_message(
        self,
        *,
        user_id: str,
        knowledge_base_id: str,
        role: KnowledgeMessageRole,
        content: str,
    ) -> KnowledgeMessageDocument:
        now = datetime.utcnow()
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "knowledge_base_id": knowledge_base_id,
            "role": role,
            "content": content,
            "created_at": now,
        }
        self.message_collection.insert_one(document)
        self.base_collection.find_one_and_update(
            {"_id": knowledge_base_id, "user_id": user_id},
            {"$set": {"updated_at": now}},
        )
        return self._to_message(document)

    def append_exchange(self, *, user_id: str, knowledge_base_id: str, user_message: str, assistant_message: str) -> None:
        self.append_message(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            role="user",
            content=user_message,
        )
        self.append_message(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            role="assistant",
            content=assistant_message,
        )

    def _to_base(self, document: dict[str, Any]) -> KnowledgeBaseDocument:
        mapped = dict(document)
        mapped["_id"] = str(mapped["_id"])
        return KnowledgeBaseDocument.model_validate(mapped)

    def _to_message(self, document: dict[str, Any]) -> KnowledgeMessageDocument:
        mapped = dict(document)
        mapped["_id"] = str(mapped["_id"])
        return KnowledgeMessageDocument.model_validate(mapped)

    def _to_ingest_job(self, document: dict[str, Any]) -> KnowledgeIngestJobDocument:
        mapped = dict(document)
        mapped["_id"] = str(mapped["_id"])
        return KnowledgeIngestJobDocument.model_validate(mapped)
