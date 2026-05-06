from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

try:
    from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
except ImportError:  # pragma: no cover - optional dependency fallback
    @dataclass
    class BaseMessage:
        content: Any


    @dataclass
    class HumanMessage(BaseMessage):
        pass


    @dataclass
    class AIMessage(BaseMessage):
        pass


    @dataclass
    class SystemMessage(BaseMessage):
        pass


OutputParser = Callable[[str], str]


DEFAULT_SUMMARIZATION_TEMPLATE = """Progressively summarize the lines of conversation provided, adding onto the previous summary.

Existing summary:
{existing_summary}

New lines of conversation:
{new_lines}

Return an updated summary that preserves important facts, decisions, preferences, pending tasks, and constraints.
"""


@dataclass
class SummaryBuffer:
    llm: Any
    max_token_limit: int
    memory_key: str = "history"
    input_key: str = "input"
    output_key: str = "output"
    human_prefix: str = "Human"
    ai_prefix: str = "AI"
    output_parser: Optional[OutputParser] = None
    summarization_template: str = DEFAULT_SUMMARIZATION_TEMPLATE
    chat_history: List[BaseMessage] = field(default_factory=list)
    summary_message: Optional[SystemMessage] = None

    def get_memory_key(self) -> str:
        return self.memory_key

    def load_memory_variables(self, inputs: Dict[str, Any]) -> Dict[str, str]:
        del inputs
        messages = self._messages_for_context()
        return {self.memory_key: self._render_messages(messages)}

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        user_input = self._require_value(inputs, self.input_key)
        model_output = self._require_value(outputs, self.output_key)

        self.chat_history.append(HumanMessage(content=user_input))

        if self.output_parser is not None:
            model_output = self.output_parser(model_output)

        self.chat_history.append(AIMessage(content=model_output))

        if self._count_tokens(self._messages_for_context()) <= self.max_token_limit:
            return

        self._summarize_history()

    def clear(self) -> None:
        self.chat_history.clear()
        self.summary_message = None

    def _messages_for_context(self) -> List[BaseMessage]:
        messages: List[BaseMessage] = []
        if self.summary_message is not None:
            messages.append(self.summary_message)
        messages.extend(self.chat_history)
        return messages

    def _summarize_history(self) -> None:
        new_lines = self._render_messages(self.chat_history)
        existing_summary = ""
        if self.summary_message is not None:
            existing_summary = self.summary_message.content

        prompt = self.summarization_template.format(
            existing_summary=existing_summary or "No summary yet.",
            new_lines=new_lines,
        )
        summary = self._call_llm(prompt)
        self.summary_message = SystemMessage(content=summary)
        self.chat_history.clear()

    def _call_llm(self, prompt: str) -> str:
        if hasattr(self.llm, "invoke"):
            response = self.llm.invoke(prompt)
            return self._extract_text(response)

        if hasattr(self.llm, "predict"):
            return self._extract_text(self.llm.predict(prompt))

        raise TypeError("llm must provide either invoke(prompt) or predict(prompt)")

    def _extract_text(self, value: Any) -> str:
        if isinstance(value, str):
            return value

        content = getattr(value, "content", None)
        if isinstance(content, str):
            return content

        if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parts.append(text)
            if parts:
                return "".join(parts)

        raise TypeError("Unable to extract text content from LLM response")

    def _count_tokens(self, messages: Sequence[BaseMessage]) -> int:
        if hasattr(self.llm, "get_num_tokens_from_messages"):
            try:
                return int(self.llm.get_num_tokens_from_messages(list(messages)))
            except Exception:
                pass

        rendered = self._render_messages(messages)

        if hasattr(self.llm, "get_num_tokens"):
            try:
                return int(self.llm.get_num_tokens(rendered))
            except Exception:
                pass

        return self._estimate_tokens(rendered)

    def _estimate_tokens(self, text: str) -> int:
        # Fallback estimate when the model cannot count tokens.
        return max(1, len(text) // 4) if text else 0

    def _render_messages(self, messages: Sequence[BaseMessage]) -> str:
        lines: List[str] = []
        for message in messages:
            if isinstance(message, HumanMessage):
                prefix = self.human_prefix
            elif isinstance(message, AIMessage):
                prefix = self.ai_prefix
            elif isinstance(message, SystemMessage):
                prefix = "System"
            else:
                prefix = message.__class__.__name__

            lines.append(f"{prefix}: {self._message_text(message)}")

        return "\n".join(lines)

    def _message_text(self, message: BaseMessage) -> str:
        content = message.content
        if isinstance(content, str):
            return content
        if isinstance(content, Sequence):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parts.append(text)
            return "".join(parts)
        return str(content)

    def _require_value(self, payload: Dict[str, Any], key: str) -> str:
        if key not in payload:
            raise KeyError(f"Missing required key: {key}")

        value = payload[key]
        if value is None:
            raise ValueError(f"Value for key '{key}' cannot be None")

        if isinstance(value, str):
            return value

        return str(value)
