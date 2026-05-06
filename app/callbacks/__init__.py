from __future__ import annotations

from functools import lru_cache

from app.callbacks.logging_handler import LoggingCallbackHandler
from app.callbacks.manager import CallbackManager
from app.callbacks.token_usage import TokenUsageCallbackHandler


@lru_cache(maxsize=1)
def get_callback_manager() -> CallbackManager:
    return CallbackManager(
        handlers=[
            LoggingCallbackHandler(),
            TokenUsageCallbackHandler(),
        ]
    )

