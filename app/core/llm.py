from __future__ import annotations

import json
import time
from typing import Any

from app.callbacks import get_callback_manager
from app.core.config import Settings

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None

try:
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover
    ChatOpenAI = None


class ChatModel:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.callbacks = get_callback_manager()
        self._client: ChatOpenAI | None = None
        if settings.openai_api_key and ChatOpenAI is not None:
            http_client = None
            if httpx is not None:
                client_kwargs: dict[str, Any] = {"trust_env": False}
                if settings.openai_proxy_url:
                    client_kwargs["proxy"] = settings.openai_proxy_url
                http_client = httpx.Client(**client_kwargs)
            self._client = ChatOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.openai_model,
                temperature=0.1,
                http_client=http_client,
            )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @property
    def client(self) -> ChatOpenAI | None:
        return self._client

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        *,
        run_name: str = "llm_complete",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        start = time.perf_counter()
        prompt_tokens = self.get_num_tokens(f"{system_prompt}\n{user_prompt}")
        self.callbacks.emit(
            "on_llm_start",
            {
                "run_name": run_name,
                "prompt_tokens": prompt_tokens,
                "metadata": metadata or {},
                "system_prompt_preview": system_prompt[:1000],
                "user_prompt_preview": user_prompt[:2000],
            },
        )
        if not self._client:
            text = self._fallback_response(system_prompt=system_prompt, user_prompt=user_prompt)
            completion_tokens = self.get_num_tokens(text)
            self.callbacks.emit(
                "on_llm_end",
                {
                    "run_name": run_name,
                    "metadata": metadata or {},
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "model_enabled": False,
                    "output_preview": text[:2000],
                },
            )
            return text

        try:
            response = self._client.invoke(
                [
                    ("system", system_prompt),
                    ("human", user_prompt),
                ],
                temperature=temperature,
            )
            text = self.extract_text(response)
            text = text or self._fallback_response(system_prompt=system_prompt, user_prompt=user_prompt)
            completion_tokens = self.get_num_tokens(text)
            self.callbacks.emit(
                "on_llm_end",
                {
                    "run_name": run_name,
                    "metadata": metadata or {},
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "model_enabled": True,
                    "output_preview": text[:2000],
                },
            )
            return text
        except Exception as exc:
            self.callbacks.emit(
                "on_llm_error",
                {
                    "run_name": run_name,
                    "metadata": metadata or {},
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    "prompt_tokens": prompt_tokens,
                    "error": str(exc),
                    "system_prompt_preview": system_prompt[:1000],
                    "user_prompt_preview": user_prompt[:2000],
                },
            )
            text = self._fallback_response(system_prompt=system_prompt, user_prompt=user_prompt)
            completion_tokens = self.get_num_tokens(text)
            self.callbacks.emit(
                "on_llm_end",
                {
                    "run_name": run_name,
                    "metadata": metadata or {},
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "model_enabled": False,
                    "fallback": True,
                    "output_preview": text[:2000],
                },
            )
            return text

    def invoke(self, prompt: str) -> str:
        return self.complete(system_prompt="You are a helpful assistant.", user_prompt=prompt)

    def predict(self, prompt: str) -> str:
        return self.invoke(prompt)

    def get_num_tokens(self, text: str) -> int:
        if self._client is not None and hasattr(self._client, "get_num_tokens"):
            try:
                return int(self._client.get_num_tokens(text))
            except Exception:
                pass
        return max(1, len(text) // 4) if text else 0

    def json_complete(
        self,
        system_prompt: str,
        user_prompt: str,
        fallback: dict[str, Any],
        *,
        run_name: str = "json_complete",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        content = self.complete(system_prompt=system_prompt, user_prompt=user_prompt, run_name=run_name, metadata=metadata)
        if not isinstance(content, str) or not content.strip():
            return fallback
        try:
            return self._extract_json(content)
        except (ValueError, json.JSONDecodeError):
            return fallback

    def extract_text(self, value: Any) -> str:
        if isinstance(value, str):
            return value

        content = getattr(value, "content", None)
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parts.append(text)
            if parts:
                return "".join(parts)

        reasoning = getattr(value, "reasoning_content", None)
        if isinstance(reasoning, str):
            return reasoning
        return ""

    def _extract_json(self, content: str | None) -> dict[str, Any]:
        if not isinstance(content, str):
            raise ValueError("content is not a string")
        text = content.strip()
        if not text:
            raise ValueError("content is empty")
        if "```json" in text:
            text = text.split("```json", 1)[1]
            text = text.split("```", 1)[0]
        return json.loads(text)

    def _fallback_response(self, system_prompt: str, user_prompt: str) -> str:
        lower = user_prompt.lower()
        if '"handler"' in system_prompt and '"next_input"' in system_prompt:
            if (
                ("http://" in lower or "https://" in lower)
                and any(word in lower for word in ("jobs", "careers", "pagination", "ranking", "company"))
            ) or any(word in user_prompt for word in ("匹配岗位", "岗位列表", "分页", "官网招聘", "适配度", "排名")):
                return json.dumps({"handler": "job_match_list", "next_input": user_prompt}, ensure_ascii=False)
            if "resume" in lower or "简历" in user_prompt:
                return json.dumps({"handler": "resume", "next_input": user_prompt}, ensure_ascii=False)
            if any(word in lower for word in ("knowledge", "jd", "url")) or any(
                word in user_prompt for word in ("知识库", "岗位库", "链接", "网址", "匹配")
            ):
                return json.dumps({"handler": "knowledge", "next_input": user_prompt}, ensure_ascii=False)
            if any(word in lower for word in ("application", "interview", "job", "offer", "company")) or any(
                word in user_prompt for word in ("投递", "岗位", "面试", "笔试", "公司")
            ):
                return json.dumps({"handler": "application", "next_input": user_prompt}, ensure_ascii=False)
            return json.dumps({"handler": "default", "next_input": user_prompt}, ensure_ascii=False)
        return f"当前模型暂时不可用，我先基于规则处理这次请求：{user_prompt}"
