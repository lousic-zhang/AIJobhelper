from __future__ import annotations

import unittest

from app.chat.tools import KnowledgeRetrievalQATool
from app.core.config import Settings
from app.models.knowledge import KnowledgeSourceChunk
from app.services.knowledge_retrieval_service import KnowledgeRetrievalService


class FakeEmbeddingClient:
    def __init__(self, *, vector: list[float] | None = None, error: Exception | None = None) -> None:
        self.vector = vector or [0.1, 0.2, 0.3]
        self.error = error

    def create_embedding(self, text: str) -> list[float]:
        if self.error is not None:
            raise self.error
        return list(self.vector)


class KnowledgeRetrievalServiceTests(unittest.TestCase):
    def test_memory_index_replaces_same_source(self) -> None:
        service = KnowledgeRetrievalService(Settings())
        service._client = None
        first = service.index_document(
            knowledge_base_id="kb-1",
            source_url="https://example.com/jobs/backend",
            title="Backend Engineer",
            text="Go Redis\n\nPython",
        )
        second = service.index_document(
            knowledge_base_id="kb-1",
            source_url="https://example.com/jobs/backend",
            title="Backend Engineer",
            text="Go Redis only",
        )
        self.assertEqual(first, 1)
        self.assertEqual(second, 1)
        result = service.query(knowledge_base_id="kb-1", query="Python", limit=4)
        self.assertEqual(result, [])

    def test_query_falls_back_to_text_when_embedding_fails(self) -> None:
        service = KnowledgeRetrievalService(Settings())
        service._client = object()
        service._embedding_client = FakeEmbeddingClient(error=RuntimeError("embedding unavailable"))
        service._ensure_index = lambda: None
        called: dict[str, bool] = {"text": False}

        def fake_text_query(*, knowledge_base_id: str, query: str, limit: int) -> list[KnowledgeSourceChunk]:
            called["text"] = True
            return [
                KnowledgeSourceChunk(
                    source_url="https://example.com/jobs/backend",
                    title="Backend Engineer",
                    content="Go Redis MySQL",
                    score=3.0,
                )
            ]

        service._run_text_query = fake_text_query
        result = service.query(knowledge_base_id="kb-1", query="Go backend", limit=4)
        self.assertTrue(called["text"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "Backend Engineer")

    def test_query_uses_hybrid_search_when_embedding_available(self) -> None:
        service = KnowledgeRetrievalService(Settings())
        service._client = object()
        service._embedding_client = FakeEmbeddingClient(vector=[0.4, 0.5, 0.6])
        service._ensure_index = lambda: None
        called: dict[str, bool] = {"hybrid": False}

        def fake_hybrid_query(
            *,
            knowledge_base_id: str,
            query: str,
            query_vector: list[float],
            limit: int,
        ) -> list[KnowledgeSourceChunk]:
            called["hybrid"] = True
            self.assertEqual(query_vector, [0.4, 0.5, 0.6])
            return [
                KnowledgeSourceChunk(
                    source_url="https://example.com/jobs/ml",
                    title="ML Engineer",
                    content="LLM retrieval ranking",
                    score=4.0,
                )
            ]

        service._run_hybrid_query = fake_hybrid_query
        result = service.query(knowledge_base_id="kb-1", query="retrieval ranking", limit=4)
        self.assertTrue(called["hybrid"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "ML Engineer")


class KnowledgeRetrievalQAToolTests(unittest.TestCase):
    def test_tool_formats_context_blocks(self) -> None:
        retrieval_service = type(
            "Retrieval",
            (),
            {
                "query": lambda self, knowledge_base_id, query, limit=4: [
                    KnowledgeSourceChunk(
                        source_url="https://example.com/jobs/backend",
                        title="Backend Engineer",
                        content="Go Redis MySQL API development",
                        score=3.25,
                    )
                ]
            },
        )()
        tool = KnowledgeRetrievalQATool(settings=Settings(), retrieval_service=retrieval_service)
        context, sources = tool.call("kb-1", "What does this role need?")
        self.assertIn("[1] (Backend Engineer)", context)
        self.assertIn("Source: https://example.com/jobs/backend", context)
        self.assertIn("Score: 3.250", context)
        self.assertEqual(len(sources), 1)


class SettingsTests(unittest.TestCase):
    def test_embedding_settings_default_to_chat_model(self) -> None:
        settings = Settings()
        self.assertTrue(settings.openai_embedding_model)
        self.assertIsInstance(settings.openai_embedding_dimensions, int)


if __name__ == "__main__":
    unittest.main()
