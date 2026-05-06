from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.chat.agent import JobChatAgent, KnowledgeChatAgent
from app.core.config import get_settings
from app.core.db import get_database
from app.core.llm import ChatModel
from app.core.session import SessionStore
from app.models.application import (
    ApplicationCreateRequest,
    ApplicationListItem,
    ApplicationStatusUpdateRequest,
)
from app.models.chat import ChatRequest, ChatResponse
from app.models.job_match import JobMatchImportRequest, JobMatchTaskDetailResponse, JobMatchTaskDocument
from app.models.chat_session import (
    ChatSessionCreateRequest,
    ChatSessionDocument,
    ChatSessionMessageDocument,
    ChatSessionRenameRequest,
)
from app.models.knowledge import (
    KnowledgeBaseCreateRequest,
    KnowledgeBaseDocument,
    KnowledgeChatRequest,
    KnowledgeChatResponse,
    KnowledgeMessageDocument,
    KnowledgeUrlIngestRequest,
)
from app.models.resume import ResumeDocument
from app.models.user import UserDocument
from app.services.application_service import ApplicationService
from app.services.auth_service import AuthService
from app.services.browser_mcp_service import BrowserMCPService
from app.services.chat_session_service import ChatSessionService
from app.services.file_service import FileStorageService
from app.services.job_listing_extract_service import JobListingExtractService
from app.services.job_listing_fetch_service import JobListingFetchService
from app.services.job_match_service import JobMatchService
from app.services.job_match_task_service import JobMatchTaskService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.knowledge_ingest_service import KnowledgeIngestService
from app.services.knowledge_match_service import KnowledgeMatchService
from app.services.knowledge_retrieval_service import KnowledgeRetrievalService
from app.services.resume_service import ResumeService


BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

settings = get_settings()
database = get_database(settings)
session_store = SessionStore(settings=settings)
auth_service = AuthService(database=database, session_store=session_store, settings=settings)
chat_model = ChatModel(settings=settings)
resume_service = ResumeService(database=database, chat_model=chat_model)
application_service = ApplicationService(database=database)
chat_session_service = ChatSessionService(database=database)
knowledge_base_service = KnowledgeBaseService(database=database)
knowledge_retrieval_service = KnowledgeRetrievalService(settings=settings)
browser_mcp_service = BrowserMCPService(settings=settings)
knowledge_ingest_service = KnowledgeIngestService(
    settings=settings,
    knowledge_base_service=knowledge_base_service,
    retrieval_service=knowledge_retrieval_service,
    browser_service=browser_mcp_service,
)
knowledge_match_service = KnowledgeMatchService(
    chat_model=chat_model,
    resume_service=resume_service,
    retrieval_service=knowledge_retrieval_service,
)
job_listing_fetch_service = JobListingFetchService(settings=settings, browser_service=browser_mcp_service)
job_listing_extract_service = JobListingExtractService()
job_match_service = JobMatchService(chat_model=chat_model)
job_match_task_service = JobMatchTaskService(
    database=database,
    resume_service=resume_service,
    fetch_service=job_listing_fetch_service,
    extract_service=job_listing_extract_service,
    match_service=job_match_service,
)
file_storage_service = FileStorageService(upload_dir=Path(settings.upload_dir))
job_chat_agent = JobChatAgent(
    settings=settings,
    chat_model=chat_model,
    resume_service=resume_service,
    application_service=application_service,
    chat_session_service=chat_session_service,
    knowledge_base_service=knowledge_base_service,
    knowledge_ingest_service=knowledge_ingest_service,
    knowledge_retrieval_service=knowledge_retrieval_service,
    knowledge_match_service=knowledge_match_service,
    job_match_task_service=job_match_task_service,
)
knowledge_chat_agent = KnowledgeChatAgent(
    settings=settings,
    chat_model=chat_model,
    knowledge_base_service=knowledge_base_service,
    knowledge_ingest_service=knowledge_ingest_service,
    knowledge_retrieval_service=knowledge_retrieval_service,
    knowledge_match_service=knowledge_match_service,
)

app = FastAPI(title="AIJobHelper", version="0.4.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")


def template_context(request: Request, *, active: str, **extra: object) -> dict[str, object]:
    current_user = auth_service.get_current_user(request)
    return {"active": active, "current_user": current_user, **extra}


def require_page_user(request: Request) -> UserDocument:
    user = auth_service.get_current_user(request)
    if user is None:
        raise HTTPException(status_code=303, detail="redirect")
    return user


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 303 and exc.detail == "redirect":
        return RedirectResponse(url="/login", status_code=303)
    if exc.status_code == 401:
        return JSONResponse(status_code=401, content={"detail": str(exc.detail)})
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc.detail)})


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> RedirectResponse:
    current_user = auth_service.get_current_user(request)
    return RedirectResponse(url="/chat" if current_user else "/login", status_code=303)


@app.get("/login", response_class=HTMLResponse, response_model=None)
def login_page(request: Request):
    current_user = auth_service.get_current_user(request)
    if current_user:
        return RedirectResponse(url="/chat", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context=template_context(request, active="login", error=""),
    )


@app.get("/register", response_class=HTMLResponse, response_model=None)
def register_page(request: Request):
    current_user = auth_service.get_current_user(request)
    if current_user:
        return RedirectResponse(url="/chat", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context=template_context(request, active="register", error=""),
    )


@app.post("/auth/register", response_model=None)
def register_action(
    request: Request,
    email: str = Form(...),
    nickname: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    try:
        _, session = auth_service.register(
            email=email,
            nickname=nickname,
            password=password,
            confirm_password=confirm_password,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context=template_context(request, active="register", error=str(exc)),
            status_code=400,
        )

    response = RedirectResponse(url="/chat", status_code=303)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session.session_id,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/auth/login", response_model=None)
def login_action(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    try:
        _, session = auth_service.login(email=email, password=password)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context=template_context(request, active="login", error=str(exc)),
            status_code=400,
        )

    response = RedirectResponse(url="/chat", status_code=303)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session.session_id,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/auth/logout")
def logout_action(request: Request) -> RedirectResponse:
    auth_service.logout(request)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(settings.session_cookie_name)
    return response


@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request) -> HTMLResponse:
    current_user = require_page_user(request)
    chat_sessions = chat_session_service.list_sessions(current_user.id)
    if not chat_sessions:
        chat_sessions = [chat_session_service.ensure_default_session(current_user.id, settings.default_chat_id)]
    selected_chat_id = chat_sessions[0].id
    return templates.TemplateResponse(
        request=request,
        name="chat.html",
        context=template_context(
            request,
            active="chat",
            chat_id=selected_chat_id,
            chat_sessions=chat_sessions,
            current_user=current_user,
        ),
    )


@app.get("/resume", response_class=HTMLResponse)
def resume_page(request: Request) -> HTMLResponse:
    current_user = require_page_user(request)
    resume = resume_service.get_current_resume(current_user.id)
    return templates.TemplateResponse(
        request=request,
        name="resume.html",
        context=template_context(request, active="resume", resume=resume, current_user=current_user),
    )


@app.get("/applications", response_class=HTMLResponse)
def applications_page(request: Request, company: str | None = None, status: str | None = None) -> HTMLResponse:
    current_user = require_page_user(request)
    applications = application_service.list_applications(
        user_id=current_user.id,
        company=company,
        status=status,
    )
    return templates.TemplateResponse(
        request=request,
        name="applications.html",
        context=template_context(
            request,
            active="applications",
            applications=applications,
            filters={"company": company or "", "status": status or ""},
            statuses=application_service.allowed_statuses,
            current_user=current_user,
        ),
    )


@app.get("/job-matches", response_class=HTMLResponse)
def job_matches_page(request: Request) -> HTMLResponse:
    current_user = require_page_user(request)
    tasks = job_match_task_service.list_tasks(current_user.id)
    selected_task_id = tasks[0].id if tasks else ""
    return templates.TemplateResponse(
        request=request,
        name="job_matches.html",
        context=template_context(
            request,
            active="job_matches",
            tasks=tasks,
            selected_task_id=selected_task_id,
            current_user=current_user,
        ),
    )


@app.get("/knowledge", response_class=HTMLResponse)
def knowledge_page(request: Request, knowledge_base_id: str | None = None) -> HTMLResponse:
    current_user = require_page_user(request)
    knowledge_bases = knowledge_base_service.list_bases(current_user.id)
    selected_id = knowledge_base_id or (knowledge_bases[0].id if knowledge_bases else "")
    return templates.TemplateResponse(
        request=request,
        name="knowledge.html",
        context=template_context(
            request,
            active="knowledge",
            knowledge_bases=knowledge_bases,
            selected_knowledge_base_id=selected_id,
            current_user=current_user,
        ),
    )


@app.post("/api/chat", response_model=ChatResponse)
def chat_api(payload: ChatRequest, request: Request) -> ChatResponse:
    current_user = auth_service.require_api_user(request)
    return job_chat_agent.chat(current_user.id, payload)


@app.get("/api/chat-sessions", response_model=list[ChatSessionDocument])
def list_chat_sessions(request: Request) -> list[ChatSessionDocument]:
    current_user = auth_service.require_api_user(request)
    sessions = chat_session_service.list_sessions(current_user.id)
    if not sessions:
        sessions = [chat_session_service.ensure_default_session(current_user.id, settings.default_chat_id)]
    return sessions


@app.post("/api/chat-sessions", response_model=ChatSessionDocument)
def create_chat_session(payload: ChatSessionCreateRequest, request: Request) -> ChatSessionDocument:
    current_user = auth_service.require_api_user(request)
    return chat_session_service.create_session(current_user.id, payload.title)


@app.get("/api/chat-sessions/{chat_id}/messages", response_model=list[ChatSessionMessageDocument])
def list_chat_session_messages(chat_id: str, request: Request) -> list[ChatSessionMessageDocument]:
    current_user = auth_service.require_api_user(request)
    chat_session_service.require_session(current_user.id, chat_id)
    return chat_session_service.list_messages(current_user.id, chat_id, limit=200)


@app.patch("/api/chat-sessions/{chat_id}", response_model=ChatSessionDocument)
def rename_chat_session(chat_id: str, payload: ChatSessionRenameRequest, request: Request) -> ChatSessionDocument:
    current_user = auth_service.require_api_user(request)
    try:
        return chat_session_service.rename_session(current_user.id, chat_id, payload.title)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/chat-sessions/{chat_id}")
def delete_chat_session(chat_id: str, request: Request) -> JSONResponse:
    current_user = auth_service.require_api_user(request)
    try:
        chat_session_service.delete_session(current_user.id, chat_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse({"ok": True})


@app.post("/api/upload/resume")
async def upload_resume(
    request: Request,
    file: UploadFile = File(...),
    chat_id: str = Form(default=settings.default_chat_id),
) -> JSONResponse:
    current_user = auth_service.require_api_user(request)
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing file name.")

    stored_file = await file_storage_service.save_resume(file)
    try:
        result = resume_service.parse_and_save(
            user_id=current_user.id,
            file_path=stored_file.file_path,
            file_name=stored_file.file_name,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_chat_agent.remember_resume_upload(
        user_id=current_user.id,
        chat_id=chat_id,
        file_name=stored_file.file_name,
        file_path=stored_file.file_path,
        parse_result=result,
    )
    return JSONResponse(
        {
            "ok": True,
            "file_name": stored_file.file_name,
            "file_path": stored_file.file_path,
            "message": "Resume uploaded and parsed successfully. You can now review it on the resume page.",
            "resume": result.model_dump(mode="json"),
        }
    )


@app.get("/api/resume/current", response_model=ResumeDocument | None)
def current_resume(request: Request) -> ResumeDocument | None:
    current_user = auth_service.require_api_user(request)
    return resume_service.get_current_resume(current_user.id)


@app.get("/api/applications", response_model=list[ApplicationListItem])
def list_applications(request: Request, company: str | None = None, status: str | None = None) -> list[ApplicationListItem]:
    current_user = auth_service.require_api_user(request)
    return application_service.list_applications(
        user_id=current_user.id,
        company=company,
        status=status,
    )


@app.post("/api/applications", response_model=ApplicationListItem)
def create_application(payload: ApplicationCreateRequest, request: Request) -> ApplicationListItem:
    current_user = auth_service.require_api_user(request)
    try:
        return application_service.create_application(current_user.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/applications/{application_id}/status", response_model=ApplicationListItem)
def update_application_status(application_id: str, payload: ApplicationStatusUpdateRequest, request: Request) -> ApplicationListItem:
    current_user = auth_service.require_api_user(request)
    try:
        return application_service.update_status(
            application_id=application_id,
            user_id=current_user.id,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/job-matches/import")
def import_job_matches(payload: JobMatchImportRequest, request: Request) -> JSONResponse:
    current_user = auth_service.require_api_user(request)
    try:
        task = job_match_task_service.submit_task(user_id=current_user.id, source_urls=[str(item) for item in payload.urls])
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"task_id": task.id, "status": task.status})


@app.get("/api/job-matches", response_model=list[JobMatchTaskDocument])
def list_job_match_tasks(request: Request) -> list[JobMatchTaskDocument]:
    current_user = auth_service.require_api_user(request)
    return job_match_task_service.list_tasks(current_user.id)


@app.get("/api/job-matches/{task_id}", response_model=JobMatchTaskDetailResponse)
def get_job_match_task(task_id: str, request: Request) -> JobMatchTaskDetailResponse:
    current_user = auth_service.require_api_user(request)
    try:
        task = job_match_task_service.require_task(current_user.id, task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    results = job_match_task_service.list_results(current_user.id, task_id)
    return JobMatchTaskDetailResponse(task=task, results=results)


@app.get("/api/knowledge-bases", response_model=list[KnowledgeBaseDocument])
def list_knowledge_bases(request: Request) -> list[KnowledgeBaseDocument]:
    current_user = auth_service.require_api_user(request)
    return knowledge_base_service.list_bases(current_user.id)


@app.post("/api/knowledge-bases", response_model=KnowledgeBaseDocument)
def create_knowledge_base(payload: KnowledgeBaseCreateRequest, request: Request) -> KnowledgeBaseDocument:
    current_user = auth_service.require_api_user(request)
    try:
        return knowledge_base_service.create_base(current_user.id, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/knowledge-bases/{knowledge_base_id}/messages", response_model=list[KnowledgeMessageDocument])
def list_knowledge_messages(knowledge_base_id: str, request: Request) -> list[KnowledgeMessageDocument]:
    current_user = auth_service.require_api_user(request)
    knowledge_base_service.require_base(current_user.id, knowledge_base_id)
    return knowledge_base_service.list_messages(current_user.id, knowledge_base_id, limit=200)


@app.post("/api/knowledge-bases/{knowledge_base_id}/ingest-url")
def ingest_knowledge_url(
    knowledge_base_id: str,
    payload: KnowledgeUrlIngestRequest,
    request: Request,
) -> JSONResponse:
    current_user = auth_service.require_api_user(request)
    try:
        result = knowledge_ingest_service.ingest_url(
            user_id=current_user.id,
            knowledge_base_id=knowledge_base_id,
            url=str(payload.url),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"ok": True, **result})


@app.post("/api/knowledge-bases/{knowledge_base_id}/chat", response_model=KnowledgeChatResponse)
def knowledge_chat(
    knowledge_base_id: str,
    payload: KnowledgeChatRequest,
    request: Request,
) -> KnowledgeChatResponse:
    current_user = auth_service.require_api_user(request)
    try:
        return knowledge_chat_agent.chat(
            user_id=current_user.id,
            knowledge_base_id=knowledge_base_id,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
