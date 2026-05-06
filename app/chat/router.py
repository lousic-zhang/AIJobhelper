from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.core.llm import ChatModel


@dataclass(frozen=True)
class HandlerDescriptor:
    name: str
    description: str


@dataclass(frozen=True)
class RouteDecision:
    handler: str
    next_input: str
    used_fallback: bool = False


class JobRouter:
    def __init__(self, chat_model: ChatModel, handlers: Iterable[HandlerDescriptor]) -> None:
        self.chat_model = chat_model
        self.handlers = list(handlers)
        self.allowed_handlers = {handler.name for handler in self.handlers}

    def route(self, message: str, memory_text: str) -> RouteDecision:
        message = (message or "").strip()
        if not message:
            return RouteDecision(handler="default", next_input="", used_fallback=True)

        handler_descriptions = "\n".join(
            f'- {handler.name}: {handler.description}'
            for handler in self.handlers
        )
        system_prompt = (
            "You are the router for an AI job assistant. "
            "Select the single best handler for the user's latest message. "
            'Return JSON only in this exact shape: {"handler":"resume|application|knowledge|job_match_list|default","next_input":"string"}. '
            "Rules: choose resume for resume parsing, resume summary, resume highlights, or questions about the current resume. "
            "Choose application for job application records, interview progress, company application status, and record updates. "
            "Choose knowledge for knowledge base creation, job page URL import, knowledge base Q&A, or matching the current resume against a job knowledge base. "
            "Choose job_match_list for multiple job detail URLs, batch job evaluation, ranking several jobs against the current resume, or opening the matched-jobs page. "
            "Choose default for greetings, general job advice, career Q&A, and anything that does not clearly belong to the other handlers. "
            "next_input should usually be the original user message unless a small rewrite makes the downstream handler work better. "
            "The handler must be one of the candidates below.\n\n"
            f"Candidate handlers:\n{handler_descriptions}"
        )
        fallback = {"handler": "default", "next_input": message}
        payload = self.chat_model.json_complete(
            system_prompt=system_prompt,
            user_prompt=f"Conversation memory:\n{memory_text}\n\nUser message:\n{message}",
            fallback=fallback,
        )
        handler = payload.get("handler", "default")
        next_input = payload.get("next_input", message)
        if handler not in self.allowed_handlers:
            return RouteDecision(handler="default", next_input=message, used_fallback=True)
        if not isinstance(next_input, str) or not next_input.strip():
            next_input = message
        return RouteDecision(handler=handler, next_input=next_input, used_fallback=payload == fallback)
