from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from app.callbacks import get_callback_manager
from app.core.config import Settings
from app.models.knowledge import KnowledgeSourceChunk

try:
    from elasticsearch import Elasticsearch
except ImportError:  # pragma: no cover
    Elasticsearch = None


@dataclass
class IndexedKnowledgeChunk:
    knowledge_base_id: str
    source_url: str
    title: str
    content: str
    chunk_id: str


class _InMemoryKnowledgeIndex:
    def __init__(self) -> None:
        self._chunks: list[IndexedKnowledgeChunk] = []

    def replace_source(self, knowledge_base_id: str, source_url: str, chunks: list[IndexedKnowledgeChunk]) -> int:
        self._chunks = [
            item for item in self._chunks if not (item.knowledge_base_id == knowledge_base_id and item.source_url == source_url)
        ]
        self._chunks.extend(chunks)
        return len(chunks)

    def query(self, knowledge_base_id: str, query: str, limit: int) -> list[KnowledgeSourceChunk]:
        words = {word for word in re.split(r"\s+", query.lower()) if word}
        scored: list[tuple[float, IndexedKnowledgeChunk]] = []
        for chunk in self._chunks:
            if chunk.knowledge_base_id != knowledge_base_id:
                continue
            haystack = f"{chunk.title}\n{chunk.content}".lower()
            score = float(sum(1 for word in words if word in haystack))
            if score <= 0:
                continue
            scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            KnowledgeSourceChunk(
                source_url=chunk.source_url,
                title=chunk.title,
                content=chunk.content,
                score=score,
            )
            for score, chunk in scored[:limit]
        ]

    def sample_chunks(self, knowledge_base_id: str, limit: int) -> list[KnowledgeSourceChunk]:
        items = [item for item in self._chunks if item.knowledge_base_id == knowledge_base_id][:limit]
        return [
            KnowledgeSourceChunk(
                source_url=item.source_url,
                title=item.title,
                content=item.content,
                score=1.0,
            )
            for item in items
        ]


class KnowledgeRetrievalService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.callbacks = get_callback_manager()
        self.index_name = f"{settings.elasticsearch_index_prefix}-documents"
        self._memory_index = _InMemoryKnowledgeIndex()
        self._client: Elasticsearch | None = None
        if Elasticsearch is not None and settings.elasticsearch_url:
            self._client = Elasticsearch(settings.elasticsearch_url)

    def index_document(self, *, knowledge_base_id: str, source_url: str, title: str, text: str) -> int:
        start = time.perf_counter()
        self.callbacks.emit(
            "on_retriever_start",
            {
                "operation": "index_document",
                "knowledge_base_id": knowledge_base_id,
                "source_url": source_url,
            },
        )
        chunks = self._chunk_text(text=text, knowledge_base_id=knowledge_base_id, source_url=source_url, title=title)
        if not chunks:
            self.callbacks.emit(
                "on_retriever_error",
                {
                    "operation": "index_document",
                    "knowledge_base_id": knowledge_base_id,
                    "source_url": source_url,
                    "error": "empty_text",
                },
            )
            raise ValueError("The webpage text is empty and cannot be indexed into the knowledge base.")

        if self._client is None:
            count = self._memory_index.replace_source(knowledge_base_id, source_url, chunks)
            self._emit_retriever_end("index_document", knowledge_base_id, count, start, backend="memory", source_url=source_url)
            return count

        self._ensure_index()
        actions: list[dict[str, Any]] = []
        for chunk in chunks:
            actions.append(
                {
                    "index": {
                        "_index": self.index_name,
                        "_id": chunk.chunk_id,
                    }
                }
            )
            actions.append(
                {
                    "knowledge_base_id": chunk.knowledge_base_id,
                    "source_url": chunk.source_url,
                    "title": chunk.title,
                    "content": chunk.content,
                }
            )
        self._delete_existing_source(knowledge_base_id=knowledge_base_id, source_url=source_url)
        self._client.bulk(operations=actions, refresh=True)
        count = len(chunks)
        self._emit_retriever_end("index_document", knowledge_base_id, count, start, backend="elasticsearch", source_url=source_url)
        return count

    def query(self, *, knowledge_base_id: str, query: str, limit: int = 4) -> list[KnowledgeSourceChunk]:
        start = time.perf_counter()
        self.callbacks.emit(
            "on_retriever_start",
            {
                "operation": "query",
                "knowledge_base_id": knowledge_base_id,
                "query": query,
                "limit": limit,
            },
        )
        if self._client is None:
            result = self._memory_index.query(knowledge_base_id, query, limit)
            self._emit_retriever_end(
                "query",
                knowledge_base_id,
                len(result),
                start,
                backend="memory",
                query=query,
                results=result,
            )
            return result

        self._ensure_index()
        result = self._client.search(
            index=self.index_name,
            size=limit,
            query={
                "bool": {
                    "filter": [{"term": {"knowledge_base_id.keyword": knowledge_base_id}}],
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["title^2", "content"],
                            }
                        }
                    ],
                }
            },
        )
        hits = result.get("hits", {}).get("hits", [])
        items = [
            KnowledgeSourceChunk(
                source_url=hit.get("_source", {}).get("source_url", ""),
                title=hit.get("_source", {}).get("title", ""),
                content=hit.get("_source", {}).get("content", ""),
                score=float(hit.get("_score") or 0.0),
            )
            for hit in hits
        ]
        self._emit_retriever_end(
            "query",
            knowledge_base_id,
            len(items),
            start,
            backend="elasticsearch",
            query=query,
            results=items,
        )
        return items

    def sample_chunks(self, *, knowledge_base_id: str, limit: int = 4) -> list[KnowledgeSourceChunk]:
        start = time.perf_counter()
        self.callbacks.emit(
            "on_retriever_start",
            {
                "operation": "sample_chunks",
                "knowledge_base_id": knowledge_base_id,
                "limit": limit,
            },
        )
        if self._client is None:
            result = self._memory_index.sample_chunks(knowledge_base_id, limit)
            self._emit_retriever_end(
                "sample_chunks",
                knowledge_base_id,
                len(result),
                start,
                backend="memory",
                results=result,
            )
            return result

        self._ensure_index()
        result = self._client.search(
            index=self.index_name,
            size=limit,
            query={
                "bool": {
                    "filter": [{"term": {"knowledge_base_id.keyword": knowledge_base_id}}],
                    "must": [{"match_all": {}}],
                }
            },
        )
        hits = result.get("hits", {}).get("hits", [])
        items = [
            KnowledgeSourceChunk(
                source_url=hit.get("_source", {}).get("source_url", ""),
                title=hit.get("_source", {}).get("title", ""),
                content=hit.get("_source", {}).get("content", ""),
                score=float(hit.get("_score") or 0.0),
            )
            for hit in hits
        ]
        self._emit_retriever_end(
            "sample_chunks",
            knowledge_base_id,
            len(items),
            start,
            backend="elasticsearch",
            results=items,
        )
        return items

    def _ensure_index(self) -> None:
        if self._client is None:
            return
        if self._client.indices.exists(index=self.index_name):
            return
        self._client.indices.create(
            index=self.index_name,
            mappings={
                "properties": {
                    "knowledge_base_id": {"type": "keyword"},
                    "source_url": {"type": "keyword"},
                    "title": {"type": "text"},
                    "content": {"type": "text"},
                }
            },
        )

    def _delete_existing_source(self, *, knowledge_base_id: str, source_url: str) -> None:
        if self._client is None:
            return
        self._client.delete_by_query(
            index=self.index_name,
            query={
                "bool": {
                    "filter": [
                        {"term": {"knowledge_base_id.keyword": knowledge_base_id}},
                        {"term": {"source_url.keyword": source_url}},
                    ]
                }
            },
            refresh=True,
            ignore_unavailable=True,
        )

    def _chunk_text(self, *, text: str, knowledge_base_id: str, source_url: str, title: str) -> list[IndexedKnowledgeChunk]:
        normalized = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not normalized:
            return []
        paragraphs = [item.strip() for item in normalized.split("\n\n") if item.strip()]
        chunks: list[IndexedKnowledgeChunk] = []
        current_parts: list[str] = []
        current_len = 0
        chunk_index = 0
        for paragraph in paragraphs:
            candidate_len = current_len + len(paragraph) + (2 if current_parts else 0)
            if current_parts and candidate_len > 900:
                content = "\n\n".join(current_parts)
                chunks.append(
                    IndexedKnowledgeChunk(
                        knowledge_base_id=knowledge_base_id,
                        source_url=source_url,
                        title=title,
                        content=content,
                        chunk_id=f"{knowledge_base_id}:{abs(hash((source_url, chunk_index, content[:80])))}",
                    )
                )
                chunk_index += 1
                current_parts = [paragraph]
                current_len = len(paragraph)
            else:
                current_parts.append(paragraph)
                current_len = candidate_len

        if current_parts:
            content = "\n\n".join(current_parts)
            chunks.append(
                IndexedKnowledgeChunk(
                    knowledge_base_id=knowledge_base_id,
                    source_url=source_url,
                    title=title,
                    content=content,
                    chunk_id=f"{knowledge_base_id}:{abs(hash((source_url, chunk_index, content[:80])))}",
                )
            )
        return chunks

    def _emit_retriever_end(
        self,
        operation: str,
        knowledge_base_id: str,
        count: int,
        start: float,
        *,
        backend: str,
        source_url: str = "",
        query: str = "",
        results: list[KnowledgeSourceChunk] | None = None,
    ) -> None:
        self.callbacks.emit(
            "on_retriever_end",
            {
                "operation": operation,
                "knowledge_base_id": knowledge_base_id,
                "source_url": source_url,
                "query": query,
                "count": count,
                "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                "backend": backend,
                "results_preview": [
                    {
                        "title": item.title[:120],
                        "source_url": item.source_url,
                        "score": item.score,
                        "content_preview": item.content[:200],
                    }
                    for item in (results or [])[:3]
                ],
            },
        )
