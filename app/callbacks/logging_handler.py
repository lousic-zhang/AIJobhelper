from __future__ import annotations

import json
import logging
from typing import Any

from app.callbacks.base import BaseCallbackHandler


class LoggingCallbackHandler(BaseCallbackHandler):
    def __init__(self) -> None:
        root = logging.getLogger()
        if not root.handlers:
            logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        self.logger = logging.getLogger("aijobhelper.callbacks")

    def on_llm_start(self, event: dict[str, Any]) -> None:
        self.logger.info("llm_start\n%s", self._pretty(event))

    def on_llm_end(self, event: dict[str, Any]) -> None:
        self.logger.info("llm_end\n%s", self._pretty(event))

    def on_llm_error(self, event: dict[str, Any]) -> None:
        self.logger.error("llm_error\n%s", self._pretty(event))

    def on_agent_start(self, event: dict[str, Any]) -> None:
        self.logger.info("agent_start\n%s", self._pretty(event))

    def on_agent_end(self, event: dict[str, Any]) -> None:
        self.logger.info("agent_end\n%s", self._pretty(event))

    def on_agent_error(self, event: dict[str, Any]) -> None:
        self.logger.error("agent_error\n%s", self._pretty(event))

    def on_tool_start(self, event: dict[str, Any]) -> None:
        self.logger.info("tool_start\n%s", self._pretty(event))

    def on_tool_end(self, event: dict[str, Any]) -> None:
        self.logger.info("tool_end\n%s", self._pretty(event))

    def on_tool_error(self, event: dict[str, Any]) -> None:
        self.logger.error("tool_error\n%s", self._pretty(event))

    def on_retriever_start(self, event: dict[str, Any]) -> None:
        self.logger.info("retriever_start\n%s", self._pretty(event))

    def on_retriever_end(self, event: dict[str, Any]) -> None:
        self.logger.info("retriever_end\n%s", self._pretty(event))

    def on_retriever_error(self, event: dict[str, Any]) -> None:
        self.logger.error("retriever_error\n%s", self._pretty(event))

    def on_custom_event(self, name: str, event: dict[str, Any]) -> None:
        self.logger.info("custom_event[%s]\n%s", name, self._pretty(event))

    def _json(self, value: dict[str, Any]) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return str(value)

    def _pretty(self, value: dict[str, Any]) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, default=str, indent=2)
        except Exception:
            return str(value)
