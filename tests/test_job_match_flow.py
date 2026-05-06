from __future__ import annotations

import unittest
from datetime import datetime

from app.chat.router import JobRouter
from app.core.config import Settings
from app.core.db import InMemoryDatabase
from app.core.llm import ChatModel
from app.models.resume import ResumeProfile
from app.services.job_listing_extract_service import JobListingExtractService
from app.services.job_listing_fetch_service import BrowserFetchedPage
from app.services.job_match_service import JobMatchService
from app.services.job_match_task_service import JobMatchTaskService
from app.services.resume_service import ResumeService


class RouterTests(unittest.TestCase):
    def test_router_routes_multiple_job_urls_to_job_match_handler(self) -> None:
        settings = Settings()
        chat_model = ChatModel(settings=settings)
        router = JobRouter(
            chat_model=chat_model,
            handlers=[
                type("Handler", (), {"name": "resume", "description": "resume"})(),
                type("Handler", (), {"name": "application", "description": "application"})(),
                type("Handler", (), {"name": "knowledge", "description": "knowledge"})(),
                type("Handler", (), {"name": "job_match_list", "description": "job match"})(),
                type("Handler", (), {"name": "default", "description": "default"})(),
            ],
        )
        decision = router.route(
            "帮我评估这几个岗位 https://careers.example.com/jobs/1 https://careers.example.com/jobs/2",
            "",
        )
        self.assertEqual(decision.handler, "job_match_list")


class JobListingExtractTests(unittest.TestCase):
    def test_collect_detail_urls_filters_same_domain_job_pages(self) -> None:
        service = JobListingExtractService()
        pages = [
            BrowserFetchedPage(
                url="https://careers.example.com/jobs/backend-1",
                raw_content="Backend Engineer 招聘 Go Redis",
                title="Backend Engineer",
            ),
            BrowserFetchedPage(
                url="https://careers.example.com/jobs/backend-2",
                raw_content="Backend Engineer 招聘 Python",
                title="Backend Engineer II",
            ),
            BrowserFetchedPage(
                url="https://other.example.com/jobs/backend-3",
                raw_content="Backend Engineer 招聘",
                title="Backend Engineer III",
            ),
            BrowserFetchedPage(
                url="https://careers.example.com/about",
                raw_content="Company history",
                title="About",
            ),
        ]
        urls = service.collect_detail_urls(pages, "https://careers.example.com/jobs", max_results=10)
        self.assertEqual(
            urls,
            [
                "https://careers.example.com/jobs/backend-1",
                "https://careers.example.com/jobs/backend-2",
            ],
        )


class JobMatchTaskServiceTests(unittest.TestCase):
    def test_create_task_requires_resume(self) -> None:
        settings = Settings()
        chat_model = ChatModel(settings=settings)
        database = InMemoryDatabase()
        resume_service = ResumeService(database=database, chat_model=chat_model)
        fetch_service = type("Fetch", (), {"settings": settings})()
        extract_service = JobListingExtractService()
        match_service = JobMatchService(chat_model=chat_model)
        task_service = JobMatchTaskService(
            database=database,
            resume_service=resume_service,
            fetch_service=fetch_service,
            extract_service=extract_service,
            match_service=match_service,
        )
        with self.assertRaises(ValueError):
            task_service.create_task("u1", ["https://careers.example.com/jobs/1"])

    def test_create_task_sets_initial_progress(self) -> None:
        settings = Settings()
        chat_model = ChatModel(settings=settings)
        database = InMemoryDatabase()
        resume_service = ResumeService(database=database, chat_model=chat_model)
        database["resumes"].replace_one(
            {"user_id": "u1"},
            {
                "_id": "u1",
                "user_id": "u1",
                "file_name": "resume.pdf",
                "file_path": "resume.pdf",
                "uploaded_at": datetime.utcnow(),
                "raw_text": "test",
                "parsed_profile": ResumeProfile().model_dump(mode="json"),
                "source": "chat_upload",
            },
            upsert=True,
        )
        fetch_service = type("Fetch", (), {"settings": settings})()
        extract_service = JobListingExtractService()
        match_service = JobMatchService(chat_model=chat_model)
        task_service = JobMatchTaskService(
            database=database,
            resume_service=resume_service,
            fetch_service=fetch_service,
            extract_service=extract_service,
            match_service=match_service,
        )
        task = task_service.create_task(
            "u1",
            ["https://careers.example.com/jobs/1", "https://careers.example.com/jobs/2"],
        )
        self.assertEqual(task.current_stage, "queued")
        self.assertTrue(task.progress_message)
        self.assertEqual(len(task.source_urls), 2)

    def test_match_service_scores_backend_job(self) -> None:
        settings = Settings()
        chat_model = ChatModel(settings=settings)
        match_service = JobMatchService(chat_model=chat_model)
        resume = type(
            "Resume",
            (),
            {
                "parsed_profile": ResumeProfile(
                    target_role="Backend Engineer",
                    skills=["Go", "Redis", "MySQL"],
                )
            },
        )()
        job = type(
            "Job",
            (),
            {
                "title": "Backend Engineer",
                "company": "Example",
                "location": "北京",
                "source_url": "https://careers.example.com/jobs/backend-1",
                "summary_text": "Go Redis MySQL backend role",
                "jd_text": "Backend Engineer role requiring Go, Redis, MySQL and API development.",
                "keywords": ["go", "redis", "mysql", "backend", "api"],
            },
        )()
        result = match_service.match_jobs(resume, [job])[0]
        self.assertGreaterEqual(result.match_score, 50)


if __name__ == "__main__":
    unittest.main()
