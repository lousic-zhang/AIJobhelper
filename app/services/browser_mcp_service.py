from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None

try:
    from langchain_core.tools import tool
    from langchain_mcp_adapters.tools import load_mcp_tools
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent
except ImportError:  # pragma: no cover
    tool = None
    load_mcp_tools = None
    ChatOpenAI = None
    create_react_agent = None

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:  # pragma: no cover
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None


@dataclass
class BrowserPageResult:
    url: str
    title: str
    html: str
    text: str
    links: list[dict[str, str]]
    fetch_mode: str = "browser_mcp_agent"


class BrowserMCPService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = logging.getLogger("aijobhelper.browser_mcp")

    @property
    def enabled(self) -> bool:
        return bool(self.settings.browser_mcp_enabled and self.settings.browser_mcp_command)

    def fetch_rendered_page(self, url: str) -> BrowserPageResult:
        results = self.fetch_rendered_pages([url])
        if not results:
            raise RuntimeError("Browser MCP did not return any page content.")
        return results[0]

    def fetch_rendered_pages(self, urls: list[str]) -> list[BrowserPageResult]:
        if not self.enabled:
            raise RuntimeError("Browser MCP client is not enabled.")
        if not all([ClientSession, StdioServerParameters, stdio_client, tool, load_mcp_tools, ChatOpenAI, create_react_agent]):
            raise RuntimeError("Browser MCP agent dependencies are missing. Please install project dependencies first.")
        if not urls:
            return []
        return asyncio.run(self._fetch_rendered_pages(urls))

    async def _fetch_rendered_pages(self, urls: list[str]) -> list[BrowserPageResult]:
        results: list[BrowserPageResult] = []
        llm = self._build_llm()
        server_params = StdioServerParameters(
            command=self.settings.browser_mcp_command,
            args=self.settings.browser_mcp_args,
            env=self._build_env(),
        )
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    mcp_tools = await load_mcp_tools(session)
                    agent = create_react_agent(llm, mcp_tools + [self._build_save_tool(results)])
                    for index, url in enumerate(urls, start=1):
                        await self._extract_single_page(agent, url, index=index, total=len(urls), results=results)
        finally:
            async_client = getattr(llm, "http_async_client", None)
            if async_client is not None:
                await async_client.aclose()
        return results

    def _build_llm(self) -> ChatOpenAI:
        async_client = None
        if httpx is not None:
            client_kwargs: dict[str, Any] = {"trust_env": False}
            if self.settings.openai_proxy_url:
                client_kwargs["proxy"] = self.settings.openai_proxy_url
            async_client = httpx.AsyncClient(**client_kwargs)
        return ChatOpenAI(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
            model=self.settings.openai_model,
            temperature=0,
            http_async_client=async_client,
        )

    def _build_save_tool(self, results: list[BrowserPageResult]):
        @tool
        def save_page_content(url: str, title: str, text: str) -> str:
            """Save one rendered job page after Browser MCP has opened it and extracted the visible text."""
            cleaned_text = str(text or "").strip()
            cleaned_title = str(title or "").strip()
            cleaned_url = str(url or "").strip()
            results.append(
                BrowserPageResult(
                    url=cleaned_url,
                    title=cleaned_title,
                    html="",
                    text=cleaned_text,
                    links=[],
                )
            )
            self.logger.info(
                "browser_mcp_saved_page url=%s title=%s text_length=%s preview_lines=%s",
                cleaned_url,
                cleaned_title[:120],
                len(cleaned_text),
                [line.strip() for line in cleaned_text.splitlines() if line.strip()][:5],
            )
            return f"Saved page content for {cleaned_url}"

        return save_page_content

    async def _extract_single_page(
        self,
        agent: Any,
        url: str,
        *,
        index: int,
        total: int,
        results: list[BrowserPageResult],
    ) -> None:
        before_count = len(results)
        self.logger.info("browser_mcp_open_page index=%s total=%s url=%s", index, total, url)
        prompt = f"""
目标：打开网页 {url}

要求：
1. 使用浏览器工具打开这个页面。
2. 如果页面是动态渲染的，请等待页面稳定。
3. 重点等待这些正文信号之一出现：职位描述、任职要求、岗位职责、职位要求、工作职责、职位信息、岗位介绍。
4. 获取整个页面所有可见文字内容，不要只取摘要。
5. 当你拿到最终页面 URL、页面标题和完整正文后，必须调用一次 `save_page_content` 工具，把 url、title、text 保存进去。
6. 不要跳过保存步骤。
"""
        async for event in agent.astream_events(
            {"messages": [("user", prompt)]},
            config={"recursion_limit": 100},
            version="v2",
        ):
            if event["event"] == "on_tool_start":
                self.logger.info(
                    "browser_mcp_agent_tool_start name=%s input=%s",
                    event.get("name", ""),
                    event.get("data", {}).get("input", {}),
                )
            elif event["event"] == "on_tool_end":
                self.logger.info(
                    "browser_mcp_agent_tool_end name=%s",
                    event.get("name", ""),
                )

        if len(results) == before_count:
            raise RuntimeError("Browser MCP agent opened the page but did not save any extracted content.")

    def _build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.settings.browser_mcp_proxy_url:
            env["HTTP_PROXY"] = self.settings.browser_mcp_proxy_url
            env["HTTPS_PROXY"] = self.settings.browser_mcp_proxy_url
        return env
