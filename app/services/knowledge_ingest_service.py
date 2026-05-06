from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.config import Settings
from app.services.browser_mcp_service import BrowserMCPService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.knowledge_retrieval_service import KnowledgeRetrievalService

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None


@dataclass
class PageContent:
    url: str
    title: str
    text: str
    fetch_mode: str


class LegacyBrowserFetchClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def fetch(self, url: str) -> PageContent:
        if not self.settings.mcp_browser_fetch_url:
            raise RuntimeError("Legacy browser fetch URL is not configured.")
        if httpx is None:
            raise RuntimeError("httpx is required for legacy browser fetch.")

        response = httpx.post(
            self.settings.mcp_browser_fetch_url,
            json={"url": url},
            timeout=60.0,
        )
        response.raise_for_status()
        payload = response.json() if "application/json" in response.headers.get("content-type", "") else {}
        html = str(payload.get("html") or "")
        text = str(payload.get("content") or payload.get("text") or "")
        title = str(payload.get("title") or "")
        final_url = str(payload.get("url") or url)

        if not text and html:
            title, text = extract_text_from_html(html)
        if not text.strip():
            raise RuntimeError("Legacy browser fetch succeeded but returned no usable text.")
        return PageContent(url=final_url, title=title, text=text, fetch_mode="legacy_browser_fetch")


class KnowledgeIngestService:
    def __init__(
        self,
        *,
        settings: Settings,
        knowledge_base_service: KnowledgeBaseService,
        retrieval_service: KnowledgeRetrievalService,
        browser_service: BrowserMCPService | None = None,
    ) -> None:
        self.settings = settings
        self.knowledge_base_service = knowledge_base_service
        self.retrieval_service = retrieval_service
        self.browser_service = browser_service
        self.legacy_browser_client = LegacyBrowserFetchClient(settings)

    def ingest_url(self, *, user_id: str, knowledge_base_id: str, url: str) -> dict[str, Any]:
        knowledge_base = self.knowledge_base_service.require_base(user_id, knowledge_base_id)
        self.knowledge_base_service.update_base_status(
            user_id=user_id,
            knowledge_base_id=knowledge_base.id,
            status="ingesting",
            last_source_url=url,
        )

        page: PageContent | None = None
        job = self.knowledge_base_service.create_ingest_job(
            user_id=user_id,
            knowledge_base_id=knowledge_base.id,
            source_url=url,
            fetch_mode="http",
        )
        try:
            page = self._fetch_with_fallback(url)
            chunk_count = self.retrieval_service.index_document(
                knowledge_base_id=knowledge_base.id,
                source_url=page.url,
                title=page.title,
                text=page.text,
            )
            now = datetime.utcnow()
            self.knowledge_base_service.finish_ingest_job(
                user_id=user_id,
                job_id=job.id,
                status="succeeded",
                fetch_mode=page.fetch_mode,
            )
            self.knowledge_base_service.update_base_status(
                user_id=user_id,
                knowledge_base_id=knowledge_base.id,
                status="ready",
                last_source_url=url,
                last_ingested_at=now,
            )
            return {
                "knowledge_base_id": knowledge_base.id,
                "title": page.title,
                "source_url": page.url,
                "fetch_mode": page.fetch_mode,
                "chunk_count": chunk_count,
                "message": f"Imported the page into the knowledge base with {chunk_count} text chunks.",
            }
        except Exception as exc:
            error_text = str(exc)
            self.knowledge_base_service.finish_ingest_job(
                user_id=user_id,
                job_id=job.id,
                status="failed",
                error_message=error_text,
                fetch_mode=page.fetch_mode if page is not None else None,
            )
            self.knowledge_base_service.update_base_status(
                user_id=user_id,
                knowledge_base_id=knowledge_base.id,
                status="failed",
                last_source_url=url,
            )
            raise ValueError(error_text) from exc

    def _fetch_with_fallback(self, url: str) -> PageContent:
        try:
            page = self._fetch_via_http(url)
            if self._looks_like_shell_page(page.text):
                raise ValueError("The page looks like a JS shell, falling back to browser rendering.")
            return page
        except Exception:
            page = self._fetch_via_browser_mcp(url)
            if page is not None:
                return page
            return self.legacy_browser_client.fetch(url)

    def _fetch_via_http(self, url: str) -> PageContent:
        if httpx is None:
            raise RuntimeError("httpx is required for URL fetching.")
        response = httpx.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
                )
            },
            timeout=30.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        title, text = extract_text_from_html(response.text)
        if not text.strip():
            raise RuntimeError("HTTP fetch succeeded but no usable text was extracted.")
        return PageContent(url=str(response.url), title=title, text=text, fetch_mode="http")

    def _fetch_via_browser_mcp(self, url: str) -> PageContent | None:
        if self.browser_service is None or not self.browser_service.enabled:
            return None
        page = self.browser_service.fetch_rendered_page(url)
        if not page.text.strip():
            return None
        return PageContent(
            url=page.url,
            title=page.title,
            text=page.text,
            fetch_mode=page.fetch_mode,
        )

    def _looks_like_shell_page(self, text: str) -> bool:
        normalized = text.lower().strip()
        if len(normalized) < 200:
            return True
        shell_markers = (
            "enable javascript",
            "you need to enable javascript",
            "loading...",
        )
        return any(marker in normalized for marker in shell_markers)


def extract_text_from_html(html: str) -> tuple[str, str]:
    title = ""
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        title = (soup.title.text or "").strip() if soup.title else ""
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        texts: list[str] = []
        for node in soup.find_all(["h1", "h2", "h3", "p", "li", "article", "section", "div"]):
            text = node.get_text(" ", strip=True)
            if text:
                texts.append(text)
        content = "\n".join(dedupe_lines(texts))
        return title, clean_text(content)

    match = re.search(r"<title>(.*?)</title>", html, flags=re.I | re.S)
    if match:
        title = match.group(1).strip()
    content = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    content = re.sub(r"<style[\s\S]*?</style>", " ", content, flags=re.I)
    content = re.sub(r"<[^>]+>", " ", content)
    return title, clean_text(content)


def dedupe_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        normalized = line.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def clean_text(text: str) -> str:
    text = re.sub(r"\r", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
