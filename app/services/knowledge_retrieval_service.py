from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any

from app.callbacks import get_callback_manager
from app.core.config import Settings
from app.models.knowledge import KnowledgeSourceChunk

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None

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


class OpenAICompatibleEmbeddingClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = bool(settings.openai_api_key and settings.openai_base_url and httpx is not None)
        self.model = settings.openai_embedding_model or settings.openai_model
        self.dimensions = settings.openai_embedding_dimensions

    def create_embedding(self, text: str) -> list[float]:
        if not self.enabled or httpx is None:
            raise RuntimeError("Embedding client is not configured.")

        payload: dict[str, Any] = {
            "model": self.model,
            "input": [text],
        }
        if self.dimensions > 0:
            payload["dimensions"] = self.dimensions

        client_kwargs: dict[str, Any] = {"trust_env": False, "timeout": 30.0}
        if self.settings.openai_proxy_url:
            client_kwargs["proxy"] = self.settings.openai_proxy_url

        with httpx.Client(**client_kwargs) as client:
            response = client.post(
                f"{self.settings.openai_base_url.rstrip('/')}/embeddings",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()

        items = data.get("data") or []
        if not items:
            raise RuntimeError("Embedding API returned no data.")
        vector = items[0].get("embedding") or []
        if not vector:
            raise RuntimeError("Embedding API returned an empty vector.")
        return [float(item) for item in vector]


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
        self._embedding_client = OpenAICompatibleEmbeddingClient(settings)
        self._vector_dimensions = settings.openai_embedding_dimensions if settings.openai_embedding_dimensions > 0 else 0
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

        vectors = self._build_chunk_vectors(chunks)
        if vectors and not self._vector_dimensions:
            first_vector = next(iter(vectors.values()), [])
            self._vector_dimensions = len(first_vector)
        self._ensure_index()
        actions: list[dict[str, Any]] = []
        for chunk in chunks:
            document: dict[str, Any] = {
                "knowledge_base_id": chunk.knowledge_base_id,
                "source_url": chunk.source_url,
                "title": chunk.title,
                "chunk_id": chunk.chunk_id,
                "content": chunk.content,
                "model_version": self._embedding_client.model,
            }
            vector = vectors.get(chunk.chunk_id)
            if vector:
                document["vector"] = vector
            actions.append(
                {
                    "index": {
                        "_index": self.index_name,
                        "_id": chunk.chunk_id,
                    }
                }
            )
            actions.append(document)

        self._delete_existing_source(knowledge_base_id=knowledge_base_id, source_url=source_url)
        self._client.bulk(operations=actions, refresh=True)
        count = len(chunks)
        backend = "elasticsearch_hybrid" if vectors else "elasticsearch_text"
        self._emit_retriever_end(
            "index_document",
            knowledge_base_id,
            count,
            start,
            backend=backend,
            source_url=source_url,
        )
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

        backend = "elasticsearch_text"
        try:
            query_vector = self._embedding_client.create_embedding(query)
            if query_vector and not self._vector_dimensions:
                self._vector_dimensions = len(query_vector)
            self._ensure_index()
            result = self._run_hybrid_query(
                knowledge_base_id=knowledge_base_id,
                query=query,
                query_vector=query_vector,
                limit=limit,
            )
            backend = "elasticsearch_hybrid"
        except Exception as exc:
            self.callbacks.emit(
                "on_retriever_error",
                {
                    "operation": "query_embedding",
                    "knowledge_base_id": knowledge_base_id,
                    "query": query,
                    "error": str(exc),
                },
            )
            self._ensure_index()
            result = self._run_text_query(knowledge_base_id=knowledge_base_id, query=query, limit=limit)

        self._emit_retriever_end(
            "query",
            knowledge_base_id,
            len(result),
            start,
            backend=backend,
            query=query,
            results=result,
        )
        return result

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
                    "filter": [{"term": {"knowledge_base_id": knowledge_base_id}}],
                    "must": [{"match_all": {}}],
                }
            },
        )
        items = self._parse_hits(result.get("hits", {}).get("hits", []))
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
        exists = self._client.indices.exists(index=self.index_name)
        if exists:
            self._client.indices.put_mapping(
                index=self.index_name,
                properties=self._mapping_properties(),
            )
            return
        self._client.indices.create(
            index=self.index_name,
            mappings={
                "properties": self._mapping_properties(),
            },
        )

    def _mapping_properties(self) -> dict[str, Any]:
        return {
            "knowledge_base_id": {"type": "keyword"},
            "source_url": {"type": "keyword"},
            "title": {"type": "text"},
            "chunk_id": {"type": "keyword"},
            "content": {"type": "text"},
            "vector": {
                "type": "dense_vector",
                "dims": self._vector_dimensions or 2048,
                "index": True,
                "similarity": "cosine",
            },
            "model_version": {"type": "keyword"},
        }

    def _delete_existing_source(self, *, knowledge_base_id: str, source_url: str) -> None:
        if self._client is None:
            return
        self._client.delete_by_query(
            index=self.index_name,
            query={
                "bool": {
                    "filter": [
                        {"term": {"knowledge_base_id": knowledge_base_id}},
                        {"term": {"source_url": source_url}},
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
                        chunk_id=self._make_chunk_id(knowledge_base_id, source_url, chunk_index, content),
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
                    chunk_id=self._make_chunk_id(knowledge_base_id, source_url, chunk_index, content),
                )
            )
        return chunks

    def _make_chunk_id(self, knowledge_base_id: str, source_url: str, chunk_index: int, content: str) -> str:
        digest = hashlib.sha1(f"{source_url}|{chunk_index}|{content[:120]}".encode("utf-8")).hexdigest()[:16]
        return f"{knowledge_base_id}:{digest}"

    def _build_chunk_vectors(self, chunks: list[IndexedKnowledgeChunk]) -> dict[str, list[float]]:
        vectors: dict[str, list[float]] = {}
        for chunk in chunks:
            try:
                vectors[chunk.chunk_id] = self._embedding_client.create_embedding(chunk.content)
            except Exception as exc:
                self.callbacks.emit(
                    "on_retriever_error",
                    {
                        "operation": "index_embedding",
                        "knowledge_base_id": chunk.knowledge_base_id,
                        "source_url": chunk.source_url,
                        "chunk_id": chunk.chunk_id,
                        "error": str(exc),
                    },
                )
                return {}
        return vectors

    def _run_text_query(self, *, knowledge_base_id: str, query: str, limit: int) -> list[KnowledgeSourceChunk]:
        if self._client is None:
            return self._memory_index.query(knowledge_base_id, query, limit)
        result = self._client.search(
            index=self.index_name,
            size=limit,
            query={
                "bool": {
                    "filter": [{"term": {"knowledge_base_id": knowledge_base_id}}],
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
        return self._parse_hits(result.get("hits", {}).get("hits", []))

    def _run_hybrid_query(
        self,
        *,
        knowledge_base_id: str,
        query: str,
        query_vector: list[float],
        limit: int,
    ) -> list[KnowledgeSourceChunk]:
        if self._client is None:
            return self._memory_index.query(knowledge_base_id, query, limit)
        result = self._client.search(
            index=self.index_name,
            size=limit,
            query={
                "bool": {
                    "filter": [{"term": {"knowledge_base_id": knowledge_base_id}}],
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
            knn={
                "field": "vector",
                "query_vector": query_vector,
                "k": max(limit * 5, limit),
                "num_candidates": max(limit * 8, limit),
                "filter": {"term": {"knowledge_base_id": knowledge_base_id}},
            },
            rescore={
                "window_size": max(limit * 5, limit),
                "query": {
                    "rescore_query": {
                        "multi_match": {
                            "query": query,
                            "fields": ["title^2", "content"],
                            "operator": "and",
                        }
                    },
                    "query_weight": 0.4,
                    "rescore_query_weight": 1.0,
                },
            },
        )
        return self._parse_hits(result.get("hits", {}).get("hits", []))

    def _parse_hits(self, hits: list[dict[str, Any]]) -> list[KnowledgeSourceChunk]:
        return [
            KnowledgeSourceChunk(
                source_url=hit.get("_source", {}).get("source_url", ""),
                title=hit.get("_source", {}).get("title", ""),
                content=hit.get("_source", {}).get("content", ""),
                score=float(hit.get("_score") or 0.0),
            )
            for hit in hits
        ]

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
