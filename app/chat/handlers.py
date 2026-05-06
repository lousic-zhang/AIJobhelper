from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.callbacks import get_callback_manager
from app.chat.router import HandlerDescriptor
from app.chat.tools import (
    ApplicationAddTool,
    ApplicationFindTool,
    ApplicationUpdateStatusTool,
    JDResumeMatchTool,
    JobMatchResultPreviewTool,
    JobMatchTaskCreateTool,
    JobMatchTaskStatusTool,
    KnowledgeBaseCreateTool,
    KnowledgeIngestFromUrlTool,
    KnowledgeRetrievalQATool,
    ResumeParseTool,
)
from app.core.config import Settings
from app.core.llm import ChatModel
from app.models.chat import ChatResponse
from app.models.knowledge import KnowledgeSourceChunk
from app.services.application_service import ApplicationService
from app.services.job_match_task_service import JobMatchTaskService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.knowledge_ingest_service import KnowledgeIngestService
from app.services.knowledge_match_service import KnowledgeMatchService
from app.services.knowledge_retrieval_service import KnowledgeRetrievalService
from app.services.resume_service import ResumeService

try:
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.tools import StructuredTool
except ImportError:  # pragma: no cover
    create_agent = None
    AIMessage = None
    HumanMessage = None
    StructuredTool = None


NO_RESUME_REPLY = "You have not uploaded a resume yet. Please upload a PDF resume on the main chat page first."
NO_KNOWLEDGE_REPLY = "No current knowledge base is selected. Please create or select one on the knowledge page first."


def with_tool_callbacks(tool_name: str, input_preview: str, fn: Callable[[], str]) -> Callable[[], str]:
    callbacks = get_callback_manager()

    def wrapped() -> str:
        start = time.perf_counter()
        callbacks.emit(
            "on_tool_start",
            {
                "tool_name": tool_name,
                "input_preview": input_preview[:300],
            },
        )
        try:
            output = fn()
            callbacks.emit(
                "on_tool_end",
                {
                    "tool_name": tool_name,
                    "output_preview": str(output)[:300],
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
            return output
        except Exception as exc:
            callbacks.emit(
                "on_tool_error",
                {
                    "tool_name": tool_name,
                    "error": str(exc),
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
            raise

    return wrapped


class DomainToolAgent:
    def __init__(self, chat_model: ChatModel) -> None:
        self.chat_model = chat_model
        self.callbacks = get_callback_manager()

    def run(
        self,
        *,
        system_prompt: str,
        user_message: str,
        memory_text: str,
        tools: list[Any],
        fallback_reply_factory: Callable[[], str] | None = None,
    ) -> tuple[str, str | None]:
        start = time.perf_counter()
        self.callbacks.emit(
            "on_agent_start",
            {
                "system_prompt_preview": system_prompt[:200],
                "user_message": user_message[:500],
                "memory_chars": len(memory_text or ""),
                "memory_preview": (memory_text or "")[:1000],
                "tool_names": [getattr(tool, "name", "") for tool in tools],
            },
        )
        if self.chat_model.client is None or create_agent is None or HumanMessage is None:
            reply = fallback_reply_factory() if fallback_reply_factory else self.chat_model.complete(system_prompt, user_message, run_name="agent_fallback_complete")
            self.callbacks.emit(
                "on_agent_end",
                {
                    "tool_name": None,
                    "used_langchain_agent": False,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    "reply_preview": reply[:1000],
                },
            )
            return reply, None

        try:
            agent = create_agent(model=self.chat_model.client, tools=tools, system_prompt=system_prompt)
            result = agent.invoke(
                {
                    "messages": [
                        HumanMessage(
                            content=(
                                f"Conversation memory:\n{memory_text or 'No memory.'}\n\n"
                                f"User message:\n{user_message}"
                            )
                        )
                    ]
                }
            )
            reply, tool_name = self._extract_agent_output(result)
            if reply:
                self.callbacks.emit(
                    "on_agent_end",
                    {
                        "tool_name": tool_name,
                        "used_langchain_agent": True,
                        "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                        "reply_preview": reply[:1000],
                    },
                )
                return reply, tool_name
        except Exception as exc:
            self.callbacks.emit(
                "on_agent_error",
                {
                    "error": str(exc),
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
            pass

        reply = fallback_reply_factory() if fallback_reply_factory else self.chat_model.complete(system_prompt, user_message, run_name="agent_error_fallback_complete")
        self.callbacks.emit(
            "on_agent_end",
            {
                "tool_name": None,
                "used_langchain_agent": False,
                "fallback_after_error": True,
                "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                "reply_preview": reply[:1000],
            },
        )
        return reply, None

    def _extract_agent_output(self, result: Any) -> tuple[str, str | None]:
        if not isinstance(result, dict):
            return "", None

        messages = result.get("messages", [])
        tool_name: str | None = None
        text = ""

        for message in reversed(messages):
            if tool_name is None and AIMessage is not None and isinstance(message, AIMessage):
                tool_calls = getattr(message, "tool_calls", None) or []
                if tool_calls:
                    tool_name = tool_calls[-1].get("name")
            content = self.chat_model.extract_text(message)
            if content and not text:
                text = content.strip()
            if text and tool_name:
                break

        if not text and "structured_response" in result and result["structured_response"] is not None:
            text = str(result["structured_response"])
        return text, tool_name


@dataclass
class BaseHandler:
    settings: Settings
    chat_model: ChatModel
    name: str
    description: str

    def descriptor(self) -> HandlerDescriptor:
        return HandlerDescriptor(name=self.name, description=self.description)

    def handle(
        self,
        user_id: str,
        chat_id: str,
        message: str,
        memory_text: str,
        context: dict[str, Any] | None = None,
    ) -> ChatResponse:
        raise NotImplementedError


class ResumeHandlerAgent(BaseHandler):
    def __init__(self, settings: Settings, chat_model: ChatModel, resume_service: ResumeService) -> None:
        super().__init__(
            settings=settings,
            chat_model=chat_model,
            name="resume",
            description="Use for current resume parsing, resume summary, resume highlights, skills, projects, or questions about the current resume.",
        )
        self.resume_service = resume_service
        self.resume_parse = ResumeParseTool(settings=settings, chat_model=chat_model, resume_service=resume_service)
        self.domain_agent = DomainToolAgent(chat_model)

    def handle(
        self,
        user_id: str,
        chat_id: str,
        message: str,
        memory_text: str,
        context: dict[str, Any] | None = None,
    ) -> ChatResponse:
        del chat_id, context
        resume = self.resume_service.get_current_resume(user_id)
        if resume is None:
            return ChatResponse(reply=NO_RESUME_REPLY, handler=self.name, tool=None, debug={"handler": self.name, "used_fallback": True})

        profile_json = json.dumps(resume.parsed_profile.model_dump(mode="json"), ensure_ascii=False)
        tool = self._build_resume_parse_tool(user_id=user_id, file_path=resume.file_path, file_name=resume.file_name)
        system_prompt = (
            "You are the resume specialist inside an AI job assistant. "
            "Answer in Chinese. "
            "You have access to the user's current structured resume profile. "
            "If the user asks to reparse, refresh, or update the current resume, call the resume_parse tool. "
            "If the user asks about resume content, summary, highlights, skills, projects, education, internships, or target role, answer directly based on the current resume profile. "
            "If information is missing, say it honestly. "
            f"Current resume profile JSON:\n{profile_json}"
        )
        reply, tool_name = self.domain_agent.run(
            system_prompt=system_prompt,
            user_message=message,
            memory_text=memory_text,
            tools=[tool] if tool is not None else [],
            fallback_reply_factory=lambda: self._fallback_resume_reply(resume),
        )
        return ChatResponse(reply=reply, handler=self.name, tool=tool_name, debug={"handler": self.name, "used_fallback": tool_name is None})

    def _build_resume_parse_tool(self, user_id: str, file_path: str, file_name: str) -> Any:
        if StructuredTool is None:
            return None

        def run_resume_parse() -> str:
            return self.resume_parse.call(user_id=user_id, file_path=file_path, file_name=file_name)

        return StructuredTool.from_function(
            func=with_tool_callbacks(self.resume_parse.name, file_name, run_resume_parse),
            name=self.resume_parse.name,
            description=self.resume_parse.description,
        )

    def _fallback_resume_reply(self, resume: Any) -> str:
        profile = resume.parsed_profile
        project_names = ", ".join(project.name for project in profile.projects[:3]) or "none"
        skills = ", ".join(profile.skills[:8]) or "none"
        return (
            f"Current resume is available. "
            f"Name: {profile.name or 'unknown'}. "
            f"School: {profile.school or 'unknown'}. "
            f"Target role: {profile.target_role or 'unknown'}. "
            f"Skills: {skills}. "
            f"Projects: {project_names}."
        )


class ApplicationHandlerAgent(BaseHandler):
    def __init__(self, settings: Settings, chat_model: ChatModel, application_service: ApplicationService) -> None:
        super().__init__(
            settings=settings,
            chat_model=chat_model,
            name="application",
            description="Use for job application records, application status, interview progress, company application lookup, or updating application records.",
        )
        self.add_tool = ApplicationAddTool(settings=settings, chat_model=chat_model, application_service=application_service)
        self.find_tool = ApplicationFindTool(settings=settings, chat_model=chat_model, application_service=application_service)
        self.update_tool = ApplicationUpdateStatusTool(settings=settings, chat_model=chat_model, application_service=application_service)
        self.domain_agent = DomainToolAgent(chat_model)

    def handle(
        self,
        user_id: str,
        chat_id: str,
        message: str,
        memory_text: str,
        context: dict[str, Any] | None = None,
    ) -> ChatResponse:
        del chat_id, context
        tools = self._build_tools(user_id=user_id, user_message=message)
        system_prompt = (
            "You are the application-record specialist inside an AI job assistant. "
            "Answer in Chinese. "
            "Use application_add when the user wants to create or record a new job application. "
            "Use application_find when the user wants to list, query, or inspect application records. "
            "Use application_update_status when the user wants to change an existing application status or interview progress. "
            "If required information is missing, ask a short follow-up question instead of guessing."
        )
        reply, tool_name = self.domain_agent.run(
            system_prompt=system_prompt,
            user_message=message,
            memory_text=memory_text,
            tools=tools,
            fallback_reply_factory=lambda: self._fallback_application_reply(user_id, message),
        )
        return ChatResponse(reply=reply, handler=self.name, tool=tool_name, debug={"handler": self.name, "used_fallback": tool_name is None})

    def _build_tools(self, user_id: str, user_message: str) -> list[Any]:
        if StructuredTool is None:
            return []

        def add_application() -> str:
            return self.add_tool.call(user_id=user_id, message=user_message)

        def find_application() -> str:
            return self.find_tool.call(user_id=user_id, message=user_message)

        def update_application_status() -> str:
            return self.update_tool.call(user_id=user_id, message=user_message)

        return [
            StructuredTool.from_function(func=with_tool_callbacks(self.add_tool.name, user_message, add_application), name=self.add_tool.name, description=self.add_tool.description),
            StructuredTool.from_function(func=with_tool_callbacks(self.find_tool.name, user_message, find_application), name=self.find_tool.name, description=self.find_tool.description),
            StructuredTool.from_function(func=with_tool_callbacks(self.update_tool.name, user_message, update_application_status), name=self.update_tool.name, description=self.update_tool.description),
        ]

    def _fallback_application_reply(self, user_id: str, message: str) -> str:
        create_keywords = ("投递了", "今天投递", "帮我记一下", "帮我做个投递记录", "新增")
        find_keywords = ("查询", "查看", "哪些", "投递情况", "列一下", "帮我查")
        update_keywords = ("状态", "更新", "改成", "拒", "一面", "二面", "笔试", "offer")

        if any(keyword in message for keyword in create_keywords):
            return self.add_tool.call(user_id=user_id, message=message)
        if any(keyword in message for keyword in find_keywords):
            return self.find_tool.call(user_id=user_id, message=message)
        if any(keyword in message for keyword in update_keywords):
            return self.update_tool.call(user_id=user_id, message=message)
        return "I can help create application records, list them, or update interview status."


class KnowledgeHandlerAgent(BaseHandler):
    def __init__(
        self,
        settings: Settings,
        chat_model: ChatModel,
        knowledge_base_service: KnowledgeBaseService,
        knowledge_ingest_service: KnowledgeIngestService,
        retrieval_service: KnowledgeRetrievalService,
        match_service: KnowledgeMatchService,
    ) -> None:
        super().__init__(
            settings=settings,
            chat_model=chat_model,
            name="knowledge",
            description="Use for knowledge base creation, job page URL import, knowledge base Q&A, and matching the current resume against the current job knowledge base.",
        )
        self.knowledge_base_service = knowledge_base_service
        self.base_create_tool = KnowledgeBaseCreateTool(settings=settings, knowledge_base_service=knowledge_base_service)
        self.ingest_tool = KnowledgeIngestFromUrlTool(settings=settings, knowledge_ingest_service=knowledge_ingest_service)
        self.retrieval_tool = KnowledgeRetrievalQATool(settings=settings, retrieval_service=retrieval_service)
        self.match_tool = JDResumeMatchTool(settings=settings, knowledge_match_service=match_service)
        self.domain_agent = DomainToolAgent(chat_model)

    def handle(
        self,
        user_id: str,
        chat_id: str,
        message: str,
        memory_text: str,
        context: dict[str, Any] | None = None,
    ) -> ChatResponse:
        del chat_id
        context = context or {}
        knowledge_base_id = context.get("knowledge_base_id")
        knowledge_base = self.knowledge_base_service.get_base(user_id, knowledge_base_id) if knowledge_base_id else None
        source_holder: dict[str, list[KnowledgeSourceChunk]] = {"sources": []}
        tools = self._build_tools(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            user_message=message,
            source_holder=source_holder,
        )

        if knowledge_base is None and not any(keyword in message for keyword in ("知识库", "岗位库", "新建", "创建")):
            return ChatResponse(reply=NO_KNOWLEDGE_REPLY, handler=self.name, tool=None, debug={"handler": self.name, "used_fallback": True, "sources": []})

        kb_summary = (
            f"Current knowledge base: {knowledge_base.name} (status={knowledge_base.status}, last_source_url={knowledge_base.last_source_url or 'none'})."
            if knowledge_base
            else "No current knowledge base selected."
        )
        system_prompt = (
            "You are the knowledge-base specialist inside an AI job assistant. "
            "Answer in Chinese. "
            "Use knowledge_base_create to create a new job knowledge base. "
            "Use knowledge_ingest_from_url to import a job page URL into the current knowledge base. "
            "Use knowledge_retrieval_qa when the user asks about the current knowledge base content. "
            "Use jd_resume_match when the user asks whether the current resume matches the current knowledge base. "
            "If a current knowledge base is required but missing, tell the user to go to the knowledge page first. "
            f"{kb_summary}"
        )
        reply, tool_name = self.domain_agent.run(
            system_prompt=system_prompt,
            user_message=message,
            memory_text=memory_text,
            tools=tools,
            fallback_reply_factory=lambda: self._fallback_knowledge_reply(
                user_id=user_id,
                message=message,
                knowledge_base=knowledge_base,
                source_holder=source_holder,
            ),
        )
        return ChatResponse(
            reply=reply,
            handler=self.name,
            tool=tool_name,
            debug={
                "handler": self.name,
                "used_fallback": tool_name is None,
                "sources": [item.model_dump(mode="json") for item in source_holder["sources"]],
            },
        )

    def _build_tools(
        self,
        *,
        user_id: str,
        knowledge_base_id: str | None,
        user_message: str,
        source_holder: dict[str, list[KnowledgeSourceChunk]],
    ) -> list[Any]:
        if StructuredTool is None:
            return []

        def create_base() -> str:
            payload = self.chat_model.json_complete(
                system_prompt='Extract the knowledge base name and return JSON only: {"name":"string"}.',
                user_prompt=user_message,
                fallback={"name": user_message.strip() or "New job knowledge base"},
            )
            return self.base_create_tool.call(user_id=user_id, name=payload.get("name") or "New job knowledge base")

        def ingest_url() -> str:
            if not knowledge_base_id:
                return NO_KNOWLEDGE_REPLY
            payload = self.chat_model.json_complete(
                system_prompt='Extract the target job page URL and return JSON only: {"url":"string"}.',
                user_prompt=user_message,
                fallback={"url": ""},
            )
            url = str(payload.get("url") or "").strip()
            if not url:
                return "Please send a full job URL."
            return self.ingest_tool.call(user_id=user_id, knowledge_base_id=knowledge_base_id, url=url)

        def retrieval_qa() -> str:
            if not knowledge_base_id:
                return NO_KNOWLEDGE_REPLY
            context, sources = self.retrieval_tool.call(knowledge_base_id=knowledge_base_id, query=user_message)
            source_holder["sources"] = sources
            return context

        def jd_match() -> str:
            if not knowledge_base_id:
                return NO_KNOWLEDGE_REPLY
            return self.match_tool.call(user_id=user_id, knowledge_base_id=knowledge_base_id)

        return [
            StructuredTool.from_function(func=with_tool_callbacks(self.base_create_tool.name, user_message, create_base), name=self.base_create_tool.name, description=self.base_create_tool.description),
            StructuredTool.from_function(func=with_tool_callbacks(self.ingest_tool.name, user_message, ingest_url), name=self.ingest_tool.name, description=self.ingest_tool.description),
            StructuredTool.from_function(func=with_tool_callbacks(self.retrieval_tool.name, user_message, retrieval_qa), name=self.retrieval_tool.name, description=self.retrieval_tool.description),
            StructuredTool.from_function(func=with_tool_callbacks(self.match_tool.name, user_message, jd_match), name=self.match_tool.name, description=self.match_tool.description),
        ]

    def _fallback_knowledge_reply(
        self,
        *,
        user_id: str,
        message: str,
        knowledge_base: Any | None,
        source_holder: dict[str, list[KnowledgeSourceChunk]],
    ) -> str:
        if knowledge_base is None:
            if "创建" in message or "新建" in message:
                payload = self.chat_model.json_complete(
                    system_prompt='Extract the knowledge base name and return JSON only: {"name":"string"}.',
                    user_prompt=message,
                    fallback={"name": "New job knowledge base"},
                )
                return self.base_create_tool.call(user_id=user_id, name=payload.get("name") or "New job knowledge base")
            return NO_KNOWLEDGE_REPLY

        if "http" in message or "链接" in message or "网址" in message or "导入" in message:
            payload = self.chat_model.json_complete(
                system_prompt='Extract the target job page URL and return JSON only: {"url":"string"}.',
                user_prompt=message,
                fallback={"url": ""},
            )
            url = str(payload.get("url") or "").strip()
            if not url:
                return "Please send a full job URL."
            return self.ingest_tool.call(user_id=user_id, knowledge_base_id=knowledge_base.id, url=url)

        if "匹配" in message or "适合" in message or "胜任" in message:
            return self.match_tool.call(user_id=user_id, knowledge_base_id=knowledge_base.id)

        context, sources = self.retrieval_tool.call(knowledge_base_id=knowledge_base.id, query=message)
        source_holder["sources"] = sources
        if not sources:
            return context
        return self.chat_model.complete(
            system_prompt="You are a job knowledge-base QA assistant. Answer in Chinese based only on the provided knowledge snippets.",
            user_prompt=f"Knowledge snippets:\n{context}\n\nUser question:\n{message}",
        )


class JobMatchListHandlerAgent(BaseHandler):
    def __init__(
        self,
        settings: Settings,
        chat_model: ChatModel,
        resume_service: ResumeService,
        job_match_task_service: JobMatchTaskService,
    ) -> None:
        super().__init__(
            settings=settings,
            chat_model=chat_model,
            name="job_match_list",
            description="Use for importing multiple job detail URLs, opening them with Browser MCP, matching them against the current resume, and sending results to the job matches page.",
        )
        self.resume_service = resume_service
        self.task_service = job_match_task_service
        self.create_tool = JobMatchTaskCreateTool(settings=settings, chat_model=chat_model, task_service=job_match_task_service)
        self.status_tool = JobMatchTaskStatusTool(settings=settings, task_service=job_match_task_service)
        self.preview_tool = JobMatchResultPreviewTool(settings=settings, task_service=job_match_task_service)
        self.domain_agent = DomainToolAgent(chat_model)

    def handle(
        self,
        user_id: str,
        chat_id: str,
        message: str,
        memory_text: str,
        context: dict[str, Any] | None = None,
    ) -> ChatResponse:
        del chat_id, context
        resume = self.resume_service.get_current_resume(user_id)
        if resume is None:
            return ChatResponse(reply=NO_RESUME_REPLY, handler=self.name, tool=None, debug={"handler": self.name, "used_fallback": True})

        tools = self._build_tools(user_id=user_id, user_message=message)
        system_prompt = (
            "You are the matched-job-list specialist inside an AI job assistant. "
            "Answer in Chinese. "
            "Use job_match_task_create when the user provides multiple job detail URLs and wants the system to open each one and rank them. "
            "Use job_match_task_status when the user asks about the latest job-match task status. "
            "Use job_match_result_preview when the user asks whether the results are ready or wants a short preview. "
            "When a new task is created, direct the user to /job-matches to view progress and results."
        )
        reply, tool_name = self.domain_agent.run(
            system_prompt=system_prompt,
            user_message=message,
            memory_text=memory_text,
            tools=tools,
            fallback_reply_factory=lambda: self._fallback_reply(user_id, message),
        )
        return ChatResponse(reply=reply, handler=self.name, tool=tool_name, debug={"handler": self.name, "used_fallback": tool_name is None})

    def _build_tools(self, user_id: str, user_message: str) -> list[Any]:
        if StructuredTool is None:
            return []

        def create_task() -> str:
            return self.create_tool.call(user_id=user_id, message=user_message)

        def latest_status() -> str:
            return self.status_tool.call(user_id=user_id)

        def preview_results() -> str:
            return self.preview_tool.call(user_id=user_id)

        return [
            StructuredTool.from_function(func=with_tool_callbacks(self.create_tool.name, user_message, create_task), name=self.create_tool.name, description=self.create_tool.description),
            StructuredTool.from_function(func=with_tool_callbacks(self.status_tool.name, user_message, latest_status), name=self.status_tool.name, description=self.status_tool.description),
            StructuredTool.from_function(func=with_tool_callbacks(self.preview_tool.name, user_message, preview_results), name=self.preview_tool.name, description=self.preview_tool.description),
        ]

    def _fallback_reply(self, user_id: str, message: str) -> str:
        if "http://" in message or "https://" in message:
            return self.create_tool.call(user_id=user_id, message=message)
        if any(keyword in message for keyword in ("结果", "完成", "抓完", "状态", "进度")):
            preview = self.preview_tool.call(user_id=user_id)
            if "最近还没有成功的匹配任务" not in preview:
                return preview
            return self.status_tool.call(user_id=user_id)
        return "你可以直接给我多个岗位详情页 URL，我会逐个打开并在 /job-matches 页面展示匹配结果。"


class DefaultHandler(BaseHandler):
    def __init__(
        self,
        settings: Settings,
        chat_model: ChatModel,
        resume_service: ResumeService,
        application_service: ApplicationService,
        knowledge_base_service: KnowledgeBaseService | None = None,
    ) -> None:
        super().__init__(
            settings=settings,
            chat_model=chat_model,
            name="default",
            description="Use for greetings, general job advice, career Q&A, and questions that do not clearly belong to resume, application records, or knowledge bases.",
        )
        self.resume_service = resume_service
        self.application_service = application_service
        self.knowledge_base_service = knowledge_base_service

    def handle(
        self,
        user_id: str,
        chat_id: str,
        message: str,
        memory_text: str,
        context: dict[str, Any] | None = None,
    ) -> ChatResponse:
        del chat_id, context
        resume = self.resume_service.get_current_resume(user_id)
        applications = self.application_service.list_applications(user_id)[:5]
        knowledge_count = len(self.knowledge_base_service.list_bases(user_id)) if self.knowledge_base_service else 0
        resume_summary = "No current resume."
        if resume:
            resume_summary = (
                f"Current resume name: {resume.parsed_profile.name or 'unknown'}. "
                f"Target role: {resume.parsed_profile.target_role or 'unknown'}."
            )
        application_summary = f"Recent application count: {len(applications)}."
        knowledge_summary = f"Knowledge base count: {knowledge_count}."
        system_prompt = "You are a helpful AI job assistant. Be concise, practical, and answer in Chinese."
        user_prompt = (
            f"Memory summary:\n{memory_text}\n\n"
            f"Resume summary:\n{resume_summary}\n\n"
            f"Application summary:\n{application_summary}\n\n"
            f"Knowledge summary:\n{knowledge_summary}\n\n"
            f"User question:\n{message}"
        )
        reply = self.chat_model.complete(system_prompt=system_prompt, user_prompt=user_prompt)
        return ChatResponse(reply=reply, handler=self.name, tool=None, debug={"handler": self.name, "used_fallback": False})
