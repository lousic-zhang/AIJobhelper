from __future__ import annotations

from threading import Lock
from typing import Any, Callable, Dict, Optional

from .summarybuffer import SummaryBuffer


class Memoryx:
    def __init__(self, factory: Callable[[], SummaryBuffer], default_chat_id: str = "default") -> None:
        self._factory = factory
        self._default_chat_id = default_chat_id
        self._lock = Lock()
        self._memories: Dict[str, SummaryBuffer] = {}
        self._default_memory = factory()

    def load_memory_variables(self, chat_id: Optional[str], inputs: Dict[str, Any]) -> Dict[str, str]:
        return self.memory(chat_id).load_memory_variables(inputs)

    def save_context(self, chat_id: Optional[str], inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        self.memory(chat_id).save_context(inputs, outputs)

    def clear(self, chat_id: Optional[str] = None) -> None:
        if chat_id is None:
            self._default_memory.clear()
            return

        self.memory(chat_id).clear()

    def memory(self, chat_id: Optional[str]) -> SummaryBuffer:
        if chat_id is None:
            return self._default_memory

        with self._lock:
            memory = self._memories.get(chat_id)
            if memory is None:
                memory = self._factory()
                self._memories[chat_id] = memory
            return memory
