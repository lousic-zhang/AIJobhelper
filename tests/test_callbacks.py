from __future__ import annotations

import unittest

from app.callbacks import get_callback_manager
from app.core.config import Settings
from app.core.llm import ChatModel


class CallbackTests(unittest.TestCase):
    def test_callback_manager_has_handlers(self) -> None:
        manager = get_callback_manager()
        self.assertGreaterEqual(len(manager.handlers), 2)

    def test_chat_model_complete_runs_with_callbacks(self) -> None:
        model = ChatModel(Settings())
        text = model.complete("You are a helper.", "Say hello.", run_name="test_complete")
        self.assertIsInstance(text, str)
        self.assertTrue(text)


if __name__ == "__main__":
    unittest.main()
