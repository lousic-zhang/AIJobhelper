from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from app.core.config import Settings
from app.services.browser_mcp_service import BrowserMCPService, BrowserPageResult


@dataclass
class BrowserFetchedPage:
    url: str
    raw_content: str
    title: str = ""


@dataclass
class BrowserFetchResult:
    pages: list[BrowserFetchedPage]


class JobListingFetchService:
    def __init__(self, settings: Settings, browser_service: BrowserMCPService | None = None) -> None:
        self.settings = settings
        self.browser_service = browser_service
        self.logger = logging.getLogger("aijobhelper.job_fetch")

    def extract_pages(self, urls: list[str]) -> BrowserFetchResult:
        if not urls:
            return BrowserFetchResult(pages=[])
        if self.browser_service is None or not self.browser_service.enabled:
            raise RuntimeError("Browser MCP is not enabled. Please start Playwright MCP and enable BROWSER_MCP.")

        pages: list[BrowserFetchedPage] = []
        for result in self._browser_fetch_many(urls):
            pages.append(BrowserFetchedPage(url=result.url, raw_content=result.text, title=result.title))
            self.logger.info(
                "browser_extract_page url=%s title=%s",
                result.url,
                result.title[:120],
            )

        call_result = BrowserFetchResult(pages=pages)
        self._log_preview("browser_extract", call_result)
        return call_result

    def _browser_fetch(self, url: str) -> BrowserPageResult | None:
        try:
            return self.browser_service.fetch_rendered_page(url) if self.browser_service is not None else None
        except Exception as exc:
            self.logger.warning("browser_mcp_fetch_failed url=%s error=%s", url, exc)
            return None

    def _browser_fetch_many(self, urls: list[str]) -> list[BrowserPageResult]:
        if self.browser_service is None:
            return []
        try:
            return self.browser_service.fetch_rendered_pages(urls)
        except Exception as exc:
            self.logger.warning("browser_mcp_batch_fetch_failed urls=%s error=%s", len(urls), exc)
            results: list[BrowserPageResult] = []
            for url in urls:
                item = self._browser_fetch(url)
                if item is not None:
                    results.append(item)
            return results

    def _log_preview(self, stage: str, result: BrowserFetchResult) -> None:
        previews: list[dict[str, Any]] = []
        for page in result.pages[:3]:
            lines = [line.strip() for line in page.raw_content.splitlines() if line.strip()]
            previews.append(
                {
                    "title": page.title[:120],
                    "url": page.url,
                    "preview_lines": lines[:5],
                }
            )
        self.logger.info(
            "%s_result pages=%s previews=%s",
            stage,
            len(result.pages),
            previews,
        )
