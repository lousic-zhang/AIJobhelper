from __future__ import annotations

from app.chat.handlers import (
    ApplicationHandlerAgent,
    DefaultHandler,
    JobMatchListHandlerAgent,
    KnowledgeHandlerAgent,
    ResumeHandlerAgent,
)
from app.chat.router import JobRouter
from app.core.config import Settings
from app.core.llm import ChatModel
from app.models.chat import ChatRequest, ChatResponse
from app.models.knowledge import KnowledgeChatRequest, KnowledgeChatResponse
from app.models.resume import ResumeDocument
from app.services.application_service import ApplicationService
from app.services.chat_session_service import ChatSessionService
from app.services.job_match_task_service import JobMatchTaskService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.knowledge_ingest_service import KnowledgeIngestService
from app.services.knowledge_match_service import KnowledgeMatchService
from app.services.knowledge_retrieval_service import KnowledgeRetrievalService
from app.services.resume_service import ResumeService
from pkg import Memoryx, SummaryBuffer


class JobChatAgent:
    def __init__(
        self,
        settings: Settings,
        chat_model: ChatModel,
        resume_service: ResumeService,
        application_service: ApplicationService,
        chat_session_service: ChatSessionService,
        knowledge_base_service: KnowledgeBaseService,
        knowledge_ingest_service: KnowledgeIngestService,
        knowledge_retrieval_service: KnowledgeRetrievalService,
        knowledge_match_service: KnowledgeMatchService,
        job_match_task_service: JobMatchTaskService,
    ) -> None:
        self.settings = settings
        self.chat_model = chat_model
        self.resume_service = resume_service
        self.application_service = application_service
        self.chat_session_service = chat_session_service
        self.knowledge_base_service = knowledge_base_service
        self.memory = Memoryx(
            lambda: SummaryBuffer(
                llm=chat_model,
                max_token_limit=2000,
                input_key="input",
                output_key="output",
            )
        )
        self.handlers = {
            "resume": ResumeHandlerAgent(
                settings=settings,
                chat_model=chat_model,
                resume_service=resume_service,
            ),
            "application": ApplicationHandlerAgent(
                settings=settings,
                chat_model=chat_model,
                application_service=application_service,
            ),
            "knowledge": KnowledgeHandlerAgent(
                settings=settings,
                chat_model=chat_model,
                knowledge_base_service=knowledge_base_service,
                knowledge_ingest_service=knowledge_ingest_service,
                retrieval_service=knowledge_retrieval_service,
                match_service=knowledge_match_service,
            ),
            "job_match_list": JobMatchListHandlerAgent(
                settings=settings,
                chat_model=chat_model,
                resume_service=resume_service,
                job_match_task_service=job_match_task_service,
            ),
            "default": DefaultHandler(
                settings=settings,
                chat_model=chat_model,
                resume_service=resume_service,
                application_service=application_service,
                knowledge_base_service=knowledge_base_service,
            ),
        }
        self.router = JobRouter(
            chat_model=chat_model,
            handlers=[handler.descriptor() for handler in self.handlers.values()],
        )

    def chat(self, user_id: str, payload: ChatRequest) -> ChatResponse:
        self.chat_session_service.ensure_default_session(user_id=user_id, chat_id=payload.chat_id)
        memory_key = self._memory_key(user_id=user_id, chat_id=payload.chat_id)
        runtime_memory = self.memory.load_memory_variables(memory_key, {}).get("history", "")
        persistent_messages = self.chat_session_service.list_messages(user_id, payload.chat_id, limit=20)
        persistent_text = "\n".join(f"{message.role}: {message.content}" for message in persistent_messages)
        memory_text = "\n".join(part for part in (persistent_text, runtime_memory) if part.strip())
        decision = self.router.route(payload.message, memory_text)
        handler = self.handlers.get(decision.handler, self.handlers["default"])
        result = handler.handle(
            user_id=user_id,
            chat_id=payload.chat_id,
            message=decision.next_input,
            memory_text=memory_text,
        )
        debug = dict(result.debug or {})
        debug.setdefault("routed_handler", decision.handler)
        debug.setdefault("router_fallback", decision.used_fallback)
        result.debug = debug
        self.memory.save_context(
            memory_key,
            {"input": payload.message},
            {"output": result.reply},
        )
        self.chat_session_service.append_exchange(
            user_id=user_id,
            chat_id=payload.chat_id,
            user_message=payload.message,
            assistant_message=result.reply,
        )
        self.chat_session_service.maybe_update_title_from_message(
            user_id=user_id,
            chat_id=payload.chat_id,
            message=payload.message,
        )
        return result

    def remember_resume_upload(
        self,
        user_id: str,
        chat_id: str,
        file_name: str,
        file_path: str,
        parse_result: ResumeDocument,
    ) -> None:
        user_text = f"User uploaded a resume file: {file_name}. Path: {file_path}"
        assistant_text = (
            f"Resume parsing finished. Current name: {parse_result.parsed_profile.name or 'unknown'}. "
            f"Target role: {parse_result.parsed_profile.target_role or 'unknown'}. "
            "The resume page has been updated."
        )
        self.memory.save_context(
            self._memory_key(user_id=user_id, chat_id=chat_id),
            {"input": user_text},
            {"output": assistant_text},
        )

    def _memory_key(self, user_id: str, chat_id: str) -> str:
        return f"{user_id}:{chat_id}"


class KnowledgeChatAgent:
    def __init__(
        self,
        *,
        settings: Settings,
        chat_model: ChatModel,
        knowledge_base_service: KnowledgeBaseService,
        knowledge_ingest_service: KnowledgeIngestService,
        knowledge_retrieval_service: KnowledgeRetrievalService,
        knowledge_match_service: KnowledgeMatchService,
    ) -> None:
        self.settings = settings
        self.knowledge_base_service = knowledge_base_service
        self.memory = Memoryx(
            lambda: SummaryBuffer(
                llm=chat_model,
                max_token_limit=2000,
                input_key="input",
                output_key="output",
            )
        )
        self.handler = KnowledgeHandlerAgent(
            settings=settings,
            chat_model=chat_model,
            knowledge_base_service=knowledge_base_service,
            knowledge_ingest_service=knowledge_ingest_service,
            retrieval_service=knowledge_retrieval_service,
            match_service=knowledge_match_service,
        )

    def chat(self, *, user_id: str, knowledge_base_id: str, payload: KnowledgeChatRequest) -> KnowledgeChatResponse:
        self.knowledge_base_service.require_base(user_id, knowledge_base_id)
        memory_key = f"knowledge:{user_id}:{knowledge_base_id}"
        persistent_messages = self.knowledge_base_service.list_messages(user_id, knowledge_base_id, limit=20)
        memory_text = self.memory.load_memory_variables(memory_key, {}).get("history", "")
        persistent_text = "\n".join(f"{message.role}: {message.content}" for message in persistent_messages)
        merged_memory = "\n".join(part for part in (persistent_text, memory_text) if part.strip())
        result = self.handler.handle(
            user_id=user_id,
            chat_id=knowledge_base_id,
            message=payload.message,
            memory_text=merged_memory,
            context={"knowledge_base_id": knowledge_base_id},
        )
        self.knowledge_base_service.append_exchange(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            user_message=payload.message,
            assistant_message=result.reply,
        )
        self.memory.save_context(
            memory_key,
            {"input": payload.message},
            {"output": result.reply},
        )
        return KnowledgeChatResponse(
            reply=result.reply,
            handler=result.handler,
            tool=result.tool,
            sources=result.debug.get("sources", []) if result.debug else [],
            debug=result.debug,
        )
