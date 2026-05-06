from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from app.core.config import Settings
from app.core.llm import ChatModel
from app.models.application import ApplicationCreateRequest
from app.models.knowledge import KnowledgeSourceChunk
from app.services.application_service import ApplicationService
from app.services.job_match_task_service import JobMatchTaskService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.knowledge_ingest_service import KnowledgeIngestService
from app.services.knowledge_match_service import KnowledgeMatchService
from app.services.knowledge_retrieval_service import KnowledgeRetrievalService
from app.services.resume_service import ResumeService


def as_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


ALLOWED_APPLICATION_STATUSES = {
    "applied",
    "written_test",
    "interview",
    "hr_interview",
    "offer",
    "rejected",
    "closed",
}


def normalize_application_status(value: Any, default: str) -> str:
    text = as_text(value, "").strip()
    return text if text in ALLOWED_APPLICATION_STATUSES else default


def parse_natural_datetime(text: Any) -> datetime | None:
    today = date.today()
    text = as_text(text).strip()
    if not text:
        return None

    if "今天" in text:
        base_day = today
    elif "明天" in text:
        base_day = today + timedelta(days=1)
    elif "后天" in text:
        base_day = today + timedelta(days=2)
    else:
        full_match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", text)
        if full_match:
            year, month, day_num, hour, minute = map(int, full_match.groups())
            return datetime(year, month, day_num, hour, minute)

        short_match = re.search(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", text)
        if short_match:
            month, day_num, hour, minute = map(int, short_match.groups())
            return datetime(today.year, month, day_num, hour, minute)
        return None

    hour = 9
    minute = 0
    hm_match = re.search(r"(\d{1,2})[:点时](\d{1,2})?", text)
    if hm_match:
        hour = int(hm_match.group(1))
        minute = int(hm_match.group(2) or 0)
    if "下午" in text or "晚上" in text:
        if hour < 12:
            hour += 12
    return datetime.combine(base_day, time(hour=hour, minute=minute))


def guess_company(message: str) -> str:
    mapping = {
        "腾讯": "腾讯",
        "字节": "字节跳动",
        "美团": "美团",
        "阿里": "阿里巴巴",
        "小米": "小米",
        "京东": "京东",
        "快手": "快手",
        "百度": "百度",
    }
    for key, value in mapping.items():
        if key in message:
            return value
    return "未识别公司"


@dataclass
class ResumeParseTool:
    settings: Settings
    chat_model: ChatModel
    resume_service: ResumeService
    name: str = "resume_parse"
    description: str = "重新解析当前用户已经上传的简历，并刷新个人简历页。"

    def call(self, user_id: str, file_path: str, file_name: str) -> str:
        resume = self.resume_service.parse_and_save(
            user_id=user_id,
            file_path=file_path,
            file_name=file_name,
        )
        profile = resume.parsed_profile
        return (
            f"简历解析完成，个人简历页已更新。"
            f"姓名：{profile.name or '未识别'}；"
            f"目标岗位：{profile.target_role or '未识别'}；"
            f"技能数：{len(profile.skills)}。"
        )


@dataclass
class ApplicationAddTool:
    settings: Settings
    chat_model: ChatModel
    application_service: ApplicationService
    name: str = "application_add"
    description: str = "新增一条投递记录，适用于记录某家公司某个岗位的投递。"

    def call(self, user_id: str, message: str) -> str:
        payload = self.chat_model.json_complete(
            system_prompt=(
                "Extract job application fields and return JSON only. "
                "Fields: company, position, channel, status, delivery_time_text, deadline_text, note."
            ),
            user_prompt=message,
            fallback=self._fallback(message),
        )
        delivery_time = parse_natural_datetime(payload.get("delivery_time_text")) or datetime.utcnow()
        deadline = parse_natural_datetime(payload.get("deadline_text"))
        created = self.application_service.create_application(
            user_id,
            ApplicationCreateRequest(
                company=as_text(payload.get("company"), "未识别公司"),
                position=as_text(payload.get("position"), "后端开发实习生"),
                channel=as_text(payload.get("channel"), "unknown"),
                status=normalize_application_status(payload.get("status"), "applied"),
                delivery_time=delivery_time,
                deadline=deadline,
                note=as_text(payload.get("note"), ""),
            ),
        )
        return (
            f"已新增投递记录：{created.company} - {created.position}；"
            f"当前状态是 {created.status}。"
        )

    def _fallback(self, message: str) -> dict[str, str]:
        return {
            "company": guess_company(message),
            "position": "后端开发实习生",
            "channel": "unknown",
            "status": "applied",
            "delivery_time_text": "今天",
            "deadline_text": "",
            "note": message,
        }


@dataclass
class ApplicationFindTool:
    settings: Settings
    chat_model: ChatModel
    application_service: ApplicationService
    name: str = "application_find"
    description: str = "查询当前用户的投递记录，支持按公司或状态过滤。"

    def call(self, user_id: str, message: str) -> str:
        payload = self.chat_model.json_complete(
            system_prompt=(
                "Extract application query filters and return JSON only. "
                "Fields: company, status. Use empty string for missing values."
            ),
            user_prompt=message,
            fallback={"company": "", "status": ""},
        )
        items = self.application_service.list_applications(
            user_id=user_id,
            company=as_text(payload.get("company")) or None,
            status=as_text(payload.get("status")) or None,
        )
        if not items:
            return "当前没有匹配的投递记录。"
        lines = [
            f"{idx}. {item.company} - {item.position} | 状态：{item.status}"
            for idx, item in enumerate(items[:10], start=1)
        ]
        return "我帮你查到这些投递记录：\n" + "\n".join(lines)


@dataclass
class ApplicationUpdateStatusTool:
    settings: Settings
    chat_model: ChatModel
    application_service: ApplicationService
    name: str = "application_update_status"
    description: str = "更新已有投递记录的状态，例如改成笔试、一面、HR 面、offer 或 rejected。"

    def call(self, user_id: str, message: str) -> str:
        payload = self.chat_model.json_complete(
            system_prompt=(
                "Extract application status update fields and return JSON only. "
                "Fields: company, position, status, note. "
                "status must be one of applied, written_test, interview, hr_interview, offer, rejected, closed."
            ),
            user_prompt=message,
            fallback=self._fallback(message),
        )
        updated = self.application_service.update_status_by_company_position(
            user_id=user_id,
            company=as_text(payload.get("company"), "未识别公司"),
            position=as_text(payload.get("position"), "后端开发实习生"),
            status=normalize_application_status(payload.get("status"), "interview"),
            note=as_text(payload.get("note"), ""),
        )
        return f"已更新投递状态：{updated.company} - {updated.position} 现在是 {updated.status}。"

    def _fallback(self, message: str) -> dict[str, str]:
        status = "interview"
        lower = message.lower()
        if "offer" in lower:
            status = "offer"
        elif "拒" in message:
            status = "rejected"
        elif "hr" in lower:
            status = "hr_interview"
        elif "笔试" in message:
            status = "written_test"
        return {
            "company": guess_company(message),
            "position": "后端开发实习生",
            "status": status,
            "note": message,
        }


@dataclass
class KnowledgeBaseCreateTool:
    settings: Settings
    knowledge_base_service: KnowledgeBaseService
    name: str = "knowledge_base_create"
    description: str = "创建一个新的岗位知识库，知识库名称由用户指定。"

    def call(self, user_id: str, name: str) -> str:
        created = self.knowledge_base_service.create_base(user_id=user_id, name=name)
        return f"已创建知识库：{created.name}。现在可以为它导入岗位链接。"


@dataclass
class KnowledgeIngestFromUrlTool:
    settings: Settings
    knowledge_ingest_service: KnowledgeIngestService
    name: str = "knowledge_ingest_from_url"
    description: str = "将当前 URL 导入到当前知识库，内部会先 HTTP 抓取，失败后再回退到浏览器 MCP。"

    def call(self, user_id: str, knowledge_base_id: str, url: str) -> str:
        result = self.knowledge_ingest_service.ingest_url(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            url=url,
        )
        return (
            f"知识库导入完成：{result['message']} "
            f"抓取方式：{result['fetch_mode']}；"
            f"来源：{result['source_url']}。"
        )


@dataclass
class KnowledgeRetrievalQATool:
    settings: Settings
    retrieval_service: KnowledgeRetrievalService
    name: str = "knowledge_retrieval_qa"
    description: str = "基于当前知识库做检索问答，返回和当前问题最相关的知识片段。"

    def call(self, knowledge_base_id: str, query: str) -> tuple[str, list[KnowledgeSourceChunk]]:
        sources = self.retrieval_service.query(knowledge_base_id=knowledge_base_id, query=query, limit=4)
        if not sources:
            return "当前知识库里还没有匹配到相关内容。", []
        context = "\n\n".join(
            f"[来源] {item.source_url}\n[标题] {item.title}\n[内容]\n{item.content}"
            for item in sources
        )
        return context, sources


@dataclass
class JDResumeMatchTool:
    settings: Settings
    knowledge_match_service: KnowledgeMatchService
    name: str = "jd_resume_match"
    description: str = "基于当前用户简历和当前知识库岗位内容，输出岗位匹配度分析。"

    def call(self, user_id: str, knowledge_base_id: str) -> str:
        return self.knowledge_match_service.match_resume_to_base(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
        )


@dataclass
class JobMatchTaskCreateTool:
    settings: Settings
    chat_model: ChatModel
    task_service: JobMatchTaskService
    name: str = "job_match_task_create"
    description: str = "Create a background resume-match task from multiple job detail URLs. The system will open each URL with Browser MCP and score it against the current resume."

    def call(self, user_id: str, message: str) -> str:
        payload = self.chat_model.json_complete(
            system_prompt='Extract all job detail URLs and return JSON only: {"urls":["string"]}.',
            user_prompt=message,
            fallback={"urls": self._extract_urls(message)},
        )
        urls = payload.get("urls")
        if not isinstance(urls, list):
            urls = self._extract_urls(message)
        source_urls = [str(item).strip() for item in urls if str(item).strip()]
        if not source_urls:
            return "请直接发送多个岗位详情页 URL，我会逐个打开并做匹配评估。"
        task = self.task_service.submit_task(user_id=user_id, source_urls=source_urls)
        return f"我已经开始逐个打开并评估这批岗位详情页。任务 ID：{task.id}。请前往 /job-matches 查看进度和结果。"

    def _extract_urls(self, message: str) -> list[str]:
        return re.findall(r"https?://[^\s]+", message)


@dataclass
class JobMatchTaskStatusTool:
    settings: Settings
    task_service: JobMatchTaskService
    name: str = "job_match_task_status"
    description: str = "Check the latest multi-URL job-match task status."

    def call(self, user_id: str) -> str:
        task = self.task_service.latest_task(user_id=user_id)
        if task is None:
            return "你最近还没有创建过岗位匹配任务。"
        return (
            f"最近任务状态：{task.status}。"
            f"已打开详情页 {task.total_pages_found} 个，识别岗位 {task.total_jobs_found} 个，已完成匹配 {task.total_jobs_matched} 个。"
            f"{(' 错误信息：' + task.error_message) if task.error_message else ''}"
        )


@dataclass
class JobMatchResultPreviewTool:
    settings: Settings
    task_service: JobMatchTaskService
    name: str = "job_match_result_preview"
    description: str = "Preview the top matched jobs from the latest successful job-match task."

    def call(self, user_id: str) -> str:
        task = self.task_service.latest_task(user_id=user_id)
        if task is None:
            return "你最近还没有创建过岗位匹配任务。"
        if task.status != "succeeded":
            return f"最近任务还没完成，当前状态是 {task.status}。请去 /job-matches 查看实时进度。"
        results = self.task_service.preview_latest_results(user_id=user_id, limit=3)
        if not results:
            return "最近还没有成功的匹配任务结果。"
        lines = [
            f"{index}. {item.title} | 分数 {item.match_score} | {item.match_reason_short}"
            for index, item in enumerate(results, start=1)
        ]
        return "最近一次匹配任务的前 3 个岗位如下：\n" + "\n".join(lines) + "\n完整结果请前往 /job-matches 查看。"
