from __future__ import annotations

from typing import Any

from app.callbacks.base import BaseCallbackHandler


class CallbackManager:
    def __init__(self, handlers: list[BaseCallbackHandler] | None = None) -> None:
        self.handlers = handlers or []

    def emit(self, method: str, event: dict[str, Any]) -> None:
        for handler in self.handlers:
            callback = getattr(handler, method, None)
            if callback is None:
                continue
            try:
                callback(event)
            except Exception:
                continue

    def custom(self, name: str, event: dict[str, Any]) -> None:
        for handler in self.handlers:
            try:
                handler.on_custom_event(name, event)
            except Exception:
                continue

