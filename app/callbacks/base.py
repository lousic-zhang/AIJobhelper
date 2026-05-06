from __future__ import annotations

from typing import Any


class BaseCallbackHandler:
    def on_llm_start(self, event: dict[str, Any]) -> None:
        pass

    def on_llm_end(self, event: dict[str, Any]) -> None:
        pass

    def on_llm_error(self, event: dict[str, Any]) -> None:
        pass

    def on_agent_start(self, event: dict[str, Any]) -> None:
        pass

    def on_agent_end(self, event: dict[str, Any]) -> None:
        pass

    def on_agent_error(self, event: dict[str, Any]) -> None:
        pass

    def on_tool_start(self, event: dict[str, Any]) -> None:
        pass

    def on_tool_end(self, event: dict[str, Any]) -> None:
        pass

    def on_tool_error(self, event: dict[str, Any]) -> None:
        pass

    def on_retriever_start(self, event: dict[str, Any]) -> None:
        pass

    def on_retriever_end(self, event: dict[str, Any]) -> None:
        pass

    def on_retriever_error(self, event: dict[str, Any]) -> None:
        pass

    def on_custom_event(self, name: str, event: dict[str, Any]) -> None:
        pass

