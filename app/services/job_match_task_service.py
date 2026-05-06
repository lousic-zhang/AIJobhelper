from __future__ import annotations

from datetime import datetime
from threading import Lock, Thread
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from app.models.job_match import JobMatchResultDocument, JobMatchTaskDocument
from app.services.job_listing_extract_service import JobListingExtractService
from app.services.job_listing_fetch_service import JobListingFetchService
from app.services.job_match_service import JobMatchService
from app.services.resume_service import ResumeService


class JobMatchTaskService:
    def __init__(
        self,
        *,
        database: Any,
        resume_service: ResumeService,
        fetch_service: JobListingFetchService,
        extract_service: JobListingExtractService,
        match_service: JobMatchService,
    ) -> None:
        self.task_collection = database["job_match_tasks"]
        self.result_collection = database["job_match_results"]
        self.resume_service = resume_service
        self.fetch_service = fetch_service
        self.extract_service = extract_service
        self.match_service = match_service
        self._lock = Lock()
        self._running_tasks: set[str] = set()

    def create_task(self, user_id: str, source_urls: list[str]) -> JobMatchTaskDocument:
        resume = self.resume_service.get_current_resume(user_id)
        if resume is None:
            raise ValueError("You have not uploaded a resume yet. Please upload your resume first.")
        normalized_urls = self._normalize_urls(source_urls)
        if not normalized_urls:
            raise ValueError("Please provide at least one valid job detail URL.")

        first = normalized_urls[0]
        parsed = urlparse(first)
        now = datetime.utcnow()
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "source_url": first,
            "source_urls": normalized_urls,
            "source_domain": parsed.netloc.lower(),
            "status": "queued",
            "current_stage": "queued",
            "progress_message": "任务已创建，等待后台逐个打开岗位详情页。",
            "error_message": "",
            "total_pages_found": 0,
            "total_jobs_found": len(normalized_urls),
            "total_jobs_matched": 0,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        }
        self.task_collection.insert_one(document)
        return self._to_task(document)

    def submit_task(self, user_id: str, source_urls: list[str]) -> JobMatchTaskDocument:
        task = self.create_task(user_id, source_urls)
        worker = Thread(target=self._run_task, args=(task.id,), daemon=True)
        worker.start()
        return task

    def list_tasks(self, user_id: str) -> list[JobMatchTaskDocument]:
        documents = self.task_collection.find({"user_id": user_id}).sort("created_at", -1)
        return [self._to_task(document) for document in documents]

    def get_task(self, user_id: str, task_id: str) -> JobMatchTaskDocument | None:
        document = self.task_collection.find_one({"_id": task_id, "user_id": user_id})
        return self._to_task(document) if document else None

    def require_task(self, user_id: str, task_id: str) -> JobMatchTaskDocument:
        task = self.get_task(user_id, task_id)
        if task is None:
            raise ValueError("Job match task does not exist or is not accessible.")
        return task

    def list_results(self, user_id: str, task_id: str) -> list[JobMatchResultDocument]:
        documents = self.result_collection.find({"user_id": user_id, "task_id": task_id}).sort("match_rank", 1)
        return [self._to_result(document) for document in documents]

    def latest_task(self, user_id: str) -> JobMatchTaskDocument | None:
        tasks = self.list_tasks(user_id)
        return tasks[0] if tasks else None

    def preview_latest_results(self, user_id: str, limit: int = 3) -> list[JobMatchResultDocument]:
        task = self.latest_task(user_id)
        if task is None or task.status != "succeeded":
            return []
        return self.list_results(user_id, task.id)[:limit]

    def _run_task(self, task_id: str) -> None:
        with self._lock:
            if task_id in self._running_tasks:
                return
            self._running_tasks.add(task_id)

        try:
            document = self.task_collection.find_one({"_id": task_id})
            if not document:
                return

            task = self._to_task(document)
            resume = self.resume_service.get_current_resume(task.user_id)
            if resume is None:
                self._mark_failed(task.user_id, task.id, "Resume is missing. Please upload it first.")
                return

            source_urls = task.source_urls or [task.source_url]
            self._update_task(
                task.user_id,
                task.id,
                status="running",
                current_stage="starting",
                progress_message="后台任务已启动，准备通过 Browser MCP 逐个打开岗位详情页。",
                started_at=datetime.utcnow(),
                finished_at=None,
                error_message="",
                total_jobs_found=len(source_urls),
            )

            self._update_task(
                task.user_id,
                task.id,
                current_stage="extracting",
                progress_message=f"准备通过 Browser MCP 打开 {len(source_urls)} 个岗位详情页。",
            )

            detail_pages: list[Any] = []
            batch_size = 3
            total_batches = max(1, (len(source_urls) + batch_size - 1) // batch_size)
            for batch_index, start_index in enumerate(range(0, len(source_urls), batch_size), start=1):
                batch_urls = source_urls[start_index:start_index + batch_size]
                already_done = len(detail_pages)
                self._update_task(
                    task.user_id,
                    task.id,
                    current_stage="extracting",
                    progress_message=(
                        f"Browser MCP 正在依次打开岗位详情页，第 {batch_index}/{total_batches} 批，"
                        f"本批 {len(batch_urls)} 个，已完成 {already_done} 个。"
                    ),
                )
                extract_result = self.fetch_service.extract_pages(batch_urls)
                detail_pages.extend(extract_result.pages)

            if not detail_pages:
                raise ValueError("Browser MCP did not return any usable job detail pages.")

            company_name = self._guess_company_name(task.source_domain, detail_pages)
            job_listings = self.extract_service.build_job_listings(detail_pages, company_name=company_name)
            if not job_listings:
                raise ValueError("No usable job descriptions were extracted from the provided URLs.")

            self._update_task(
                task.user_id,
                task.id,
                current_stage="matching",
                progress_message=f"已抽取 {len(job_listings)} 个岗位详情，正在分析与你当前简历的匹配程度。",
                total_pages_found=len(detail_pages),
                total_jobs_found=len(job_listings),
            )

            analyses = self.match_service.match_jobs(resume, job_listings)
            self._replace_results(task.user_id, task.id, analyses)
            self._update_task(
                task.user_id,
                task.id,
                status="succeeded",
                current_stage="completed",
                total_pages_found=len(detail_pages),
                total_jobs_found=len(job_listings),
                total_jobs_matched=len(analyses),
                progress_message=f"任务完成，已完成 {len(analyses)} 个岗位的匹配评估。",
                finished_at=datetime.utcnow(),
                error_message="",
            )
        except Exception as exc:
            document = self.task_collection.find_one({"_id": task_id})
            if document:
                task = self._to_task(document)
                self._mark_failed(task.user_id, task.id, str(exc))
        finally:
            with self._lock:
                self._running_tasks.discard(task_id)

    def _replace_results(self, user_id: str, task_id: str, analyses: list[Any]) -> None:
        self.result_collection.delete_many({"user_id": user_id, "task_id": task_id})
        now = datetime.utcnow()
        for index, item in enumerate(analyses, start=1):
            document = {
                "_id": uuid4().hex,
                "task_id": task_id,
                "user_id": user_id,
                "title": item.title,
                "company": item.company,
                "location": item.location,
                "source_url": item.source_url,
                "summary_text": item.summary_text,
                "jd_text": item.jd_text,
                "keywords": item.keywords,
                "match_score": item.match_score,
                "match_rank": index,
                "match_reason_short": item.match_reason_short,
                "strengths": item.strengths,
                "gaps": item.gaps,
                "created_at": now,
            }
            self.result_collection.insert_one(document)

    def _update_task(self, user_id: str, task_id: str, **patch: Any) -> JobMatchTaskDocument:
        patch["updated_at"] = datetime.utcnow()
        document = self.task_collection.find_one_and_update(
            {"_id": task_id, "user_id": user_id},
            {"$set": patch},
        )
        if document is None:
            document = self.task_collection.find_one({"_id": task_id, "user_id": user_id})
        return self._to_task(document)

    def _mark_failed(self, user_id: str, task_id: str, error_message: str) -> None:
        self._update_task(
            user_id,
            task_id,
            status="failed",
            current_stage="failed",
            progress_message="任务失败，请查看错误信息。",
            error_message=error_message,
            finished_at=datetime.utcnow(),
        )

    def _guess_company_name(self, domain: str, pages: list[Any]) -> str:
        for page in pages:
            if getattr(page, "title", ""):
                title = page.title.split("|")[0].split("-")[0].strip()
                if len(title) >= 2:
                    return title[:80]
        host = domain.replace("www.", "")
        return host.split(".")[0].title()

    def _normalize_urls(self, source_urls: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in source_urls:
            text = str(value or "").strip()
            parsed = urlparse(text)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            if text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    def _to_task(self, document: dict[str, Any]) -> JobMatchTaskDocument:
        mapped = dict(document)
        mapped["_id"] = str(mapped["_id"])
        if "source_urls" not in mapped:
            mapped["source_urls"] = [mapped.get("source_url", "")]
        return JobMatchTaskDocument.model_validate(mapped)

    def _to_result(self, document: dict[str, Any]) -> JobMatchResultDocument:
        mapped = dict(document)
        mapped["_id"] = str(mapped["_id"])
        return JobMatchResultDocument.model_validate(mapped)
