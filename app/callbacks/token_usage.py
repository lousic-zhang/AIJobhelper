from __future__ import annotations

import logging
from typing import Any

from app.callbacks.base import BaseCallbackHandler


class TokenUsageCallbackHandler(BaseCallbackHandler):
    def __init__(self) -> None:
        root = logging.getLogger()
        if not root.handlers:
            logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        self.logger = logging.getLogger("aijobhelper.token_usage")

    def on_llm_end(self, event: dict[str, Any]) -> None:
        self.logger.info(
            "llm_usage run_name=%s duration_ms=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            event.get("run_name", ""),
            event.get("duration_ms", 0),
            event.get("prompt_tokens", 0),
            event.get("completion_tokens", 0),
            event.get("total_tokens", 0),
        )

    def on_llm_error(self, event: dict[str, Any]) -> None:
        self.logger.warning(
            "llm_usage_error run_name=%s error=%s",
            event.get("run_name", ""),
            event.get("error", ""),
        )

