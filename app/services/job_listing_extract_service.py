from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse

from app.services.job_listing_fetch_service import BrowserFetchedPage


LISTING_KEYWORDS = (
    "job",
    "jobs",
    "career",
    "careers",
    "position",
    "positions",
    "opening",
    "openings",
    "recruit",
    "campus",
    "social",
    "hiring",
    "招聘",
    "岗位",
    "职位",
    "校招",
    "社招",
    "热招",
    "加入我们",
)

ROLE_HINTS = (
    "engineer",
    "developer",
    "backend",
    "front-end",
    "frontend",
    "full stack",
    "data",
    "algorithm",
    "product",
    "design",
    "运营",
    "开发",
    "工程师",
    "算法",
    "产品",
    "设计",
    "测试",
    "客户端",
    "前端",
    "后端",
    "架构师",
)

JD_SECTION_HINTS = (
    "岗位职责",
    "任职要求",
    "职位描述",
    "职位要求",
    "工作职责",
    "工作内容",
    "岗位要求",
    "职位信息",
    "岗位介绍",
    "Responsibilities",
    "Requirements",
    "Qualifications",
)

LOCATION_HINTS = (
    "beijing",
    "shanghai",
    "shenzhen",
    "hangzhou",
    "guangzhou",
    "chengdu",
    "wuhan",
    "nanjing",
    "xian",
    "hong kong",
    "北京",
    "上海",
    "深圳",
    "杭州",
    "广州",
    "成都",
    "武汉",
    "南京",
    "西安",
    "香港",
)


@dataclass
class ExtractedJobListing:
    title: str
    company: str
    location: str
    source_url: str
    summary_text: str
    jd_text: str
    keywords: list[str]


class JobListingExtractService:
    def collect_detail_urls(self, pages: Iterable[BrowserFetchedPage], source_url: str, max_results: int) -> list[str]:
        base_domain = urlparse(source_url).netloc.lower()
        seen: set[str] = set()
        results: list[str] = []
        for page in pages:
            if not page.url:
                continue
            if urlparse(page.url).netloc.lower() != base_domain:
                continue
            if not self._looks_like_job_page(page.url, page.title, page.raw_content):
                continue
            if page.url in seen:
                continue
            seen.add(page.url)
            results.append(page.url)
            if len(results) >= max_results:
                break
        return results

    def build_job_listings(self, pages: Iterable[BrowserFetchedPage], company_name: str) -> list[ExtractedJobListing]:
        results: list[ExtractedJobListing] = []
        seen: set[str] = set()
        for page in pages:
            if not page.url or not page.raw_content:
                continue
            if page.url in seen:
                continue
            title = self._guess_title(page)
            jd_text = self._clean_text(page.raw_content)
            if len(jd_text) < 60:
                continue
            if not self._looks_like_job_detail(title, jd_text, page.url):
                continue
            location = self._extract_location(jd_text)
            keywords = self._extract_keywords(title, jd_text)
            summary = self._summarize_text(jd_text)
            results.append(
                ExtractedJobListing(
                    title=title,
                    company=company_name,
                    location=location,
                    source_url=page.url,
                    summary_text=summary,
                    jd_text=jd_text,
                    keywords=keywords,
                )
            )
            seen.add(page.url)
        return results

    def _looks_like_job_page(self, url: str, title: str, text: str) -> bool:
        haystack = f"{url}\n{title}\n{text[:3000]}".lower()
        has_listing_signal = any(keyword.lower() in haystack for keyword in LISTING_KEYWORDS)
        has_role_signal = any(keyword.lower() in haystack for keyword in ROLE_HINTS)
        has_jd_signal = any(keyword.lower() in haystack for keyword in JD_SECTION_HINTS)
        return has_jd_signal or (has_listing_signal and has_role_signal)

    def _looks_like_job_detail(self, title: str, text: str, url: str) -> bool:
        haystack = f"{url}\n{title}\n{text[:5000]}".lower()
        has_role_signal = any(keyword.lower() in haystack for keyword in ROLE_HINTS)
        has_jd_signal = any(keyword.lower() in haystack for keyword in JD_SECTION_HINTS)
        direct_job_url = any(token in haystack for token in ("/job", "job-info", "position", "岗位", "职位"))
        return has_jd_signal or has_role_signal or direct_job_url

    def _guess_title(self, page: BrowserFetchedPage) -> str:
        candidates = [page.title.strip()] if page.title else []
        candidates.extend(line.strip() for line in page.raw_content.splitlines()[:12] if line.strip())
        for item in candidates:
            if self._looks_like_title(item):
                return item[:160]
        return (page.title or "Unknown Position")[:160]

    def _looks_like_title(self, value: str) -> bool:
        if len(value) > 160 or len(value) < 2:
            return False
        lower = value.lower()
        if any(keyword.lower() in lower for keyword in ROLE_HINTS):
            return True
        return any(keyword.lower() in lower for keyword in LISTING_KEYWORDS)

    def _extract_location(self, text: str) -> str:
        lower = text.lower()
        for hint in LOCATION_HINTS:
            if hint.lower() in lower:
                return hint
        return ""

    def _extract_keywords(self, title: str, text: str) -> list[str]:
        found: list[str] = []
        haystack = f"{title}\n{text}".lower()
        samples = (
            "go",
            "golang",
            "python",
            "java",
            "c++",
            "redis",
            "mysql",
            "postgresql",
            "elasticsearch",
            "docker",
            "kubernetes",
            "fastapi",
            "langchain",
            "llm",
            "backend",
            "api",
            "data",
            "后端",
            "前端",
            "算法",
            "测试",
            "大模型",
        )
        for item in samples:
            if item in haystack:
                found.append(item)
        return found

    def _summarize_text(self, text: str) -> str:
        cleaned = [line.strip() for line in text.splitlines() if line.strip()]
        return " ".join(cleaned[:4])[:320]

    def _clean_text(self, text: str) -> str:
        normalized = re.sub(r"\r", "\n", text)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()
