from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.core.config import Settings

try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover - optional dependency fallback
    MongoClient = None


class Cursor(list):
    def sort(self, key: str, direction: int) -> "Cursor":
        reverse = direction == -1
        return Cursor(sorted(self, key=lambda item: item.get(key), reverse=reverse))


class InMemoryCollection:
    def __init__(self) -> None:
        self._documents: list[dict[str, Any]] = []

    def insert_one(self, document: dict[str, Any]) -> SimpleNamespace:
        doc = deepcopy(document)
        doc.setdefault("_id", uuid4().hex)
        self._documents.append(doc)
        return SimpleNamespace(inserted_id=doc["_id"])

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for document in self._documents:
            if self._match(document, query):
                return deepcopy(document)
        return None

    def replace_one(self, query: dict[str, Any], document: dict[str, Any], upsert: bool = False) -> None:
        for index, current in enumerate(self._documents):
            if self._match(current, query):
                self._documents[index] = deepcopy(document)
                return
        if upsert:
            self._documents.append(deepcopy(document))

    def find(self, query: dict[str, Any]) -> Cursor:
        return Cursor(deepcopy([doc for doc in self._documents if self._match(doc, query)]))

    def find_one_and_update(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        return_document: Any = None,
    ) -> dict[str, Any] | None:
        del return_document
        for index, current in enumerate(self._documents):
            if self._match(current, query):
                patch = update.get("$set", {})
                current.update(patch)
                self._documents[index] = current
                return deepcopy(current)
        return None

    def delete_one(self, query: dict[str, Any]) -> SimpleNamespace:
        deleted = 0
        for index, current in enumerate(self._documents):
            if self._match(current, query):
                del self._documents[index]
                deleted = 1
                break
        return SimpleNamespace(deleted_count=deleted)

    def delete_many(self, query: dict[str, Any]) -> SimpleNamespace:
        original = len(self._documents)
        self._documents = [doc for doc in self._documents if not self._match(doc, query)]
        return SimpleNamespace(deleted_count=original - len(self._documents))

    def _match(self, document: dict[str, Any], query: dict[str, Any]) -> bool:
        for key, value in query.items():
            current = document.get(key)
            if isinstance(value, dict) and "$regex" in value:
                import re

                flags = re.I if value.get("$options") == "i" else 0
                if not isinstance(current, str) or re.search(value["$regex"], current, flags) is None:
                    return False
                continue
            if current != value:
                return False
        return True


class InMemoryDatabase:
    def __init__(self) -> None:
        self._collections: dict[str, InMemoryCollection] = {}

    def __getitem__(self, item: str) -> InMemoryCollection:
        if item not in self._collections:
            self._collections[item] = InMemoryCollection()
        return self._collections[item]


def get_database(settings: Settings) -> Any:
    if MongoClient is None:
        return InMemoryDatabase()
    client = MongoClient(settings.mongodb_uri)
    return client[settings.mongodb_db]
