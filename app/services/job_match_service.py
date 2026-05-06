from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.core.llm import ChatModel
from app.models.resume import ResumeDocument
from app.services.job_listing_extract_service import ExtractedJobListing


@dataclass
class JobMatchAnalysis:
    title: str
    company: str
    location: str
    source_url: str
    summary_text: str
    jd_text: str
    keywords: list[str]
    match_score: int
    match_reason_short: str
    strengths: list[str]
    gaps: list[str]


class JobMatchService:
    ROLE_WEIGHT = 0.40
    SKILL_WEIGHT = 0.30
    EXPERIENCE_WEIGHT = 0.20
    LOCATION_WEIGHT = 0.10
    OVERALL_SCORE_DRIFT_LIMIT = 20

    def __init__(self, chat_model: ChatModel) -> None:
        self.chat_model = chat_model

    def match_jobs(self, resume: ResumeDocument, jobs: list[ExtractedJobListing]) -> list[JobMatchAnalysis]:
        analyses = [self._match_one(resume, job) for job in jobs]
        analyses.sort(key=lambda item: item.match_score, reverse=True)
        return analyses

    def _match_one(self, resume: ResumeDocument, job: ExtractedJobListing) -> JobMatchAnalysis:
        profile = resume.parsed_profile
        resume_skills = {item.strip().lower() for item in profile.skills if item.strip()}
        project_stack = {
            tech.strip().lower()
            for project in profile.projects
            for tech in project.tech_stack
            if tech.strip()
        }
        internship_text = " ".join(
            f"{item.company} {item.role} {item.summary}" for item in profile.internships
        ).lower()
        title_text = job.title.lower()
        jd_text = job.jd_text.lower()
        keyword_set = {item.lower() for item in job.keywords}

        role_rule_score = 0
        if profile.target_role and profile.target_role.lower() in f"{job.title} {job.jd_text}".lower():
            role_rule_score = 40
        elif any(token in title_text for token in self._split_terms(profile.target_role)):
            role_rule_score = 28
        elif "backend" in title_text or "后端" in job.title:
            role_rule_score = 20

        matched_skills = sorted((resume_skills | project_stack) & keyword_set)
        skill_rule_score = min(30, len(matched_skills) * 6)

        experience_rule_score = 0
        if profile.projects:
            experience_rule_score += 10
        if profile.internships:
            experience_rule_score += 10
        if "intern" in jd_text or "实习" in job.jd_text:
            experience_rule_score = min(20, experience_rule_score + 4)
        if any(token in internship_text for token in keyword_set):
            experience_rule_score = min(20, experience_rule_score + 4)

        location_rule_score = 0
        resume_location = (profile.contact.location or "").lower()
        if job.location and job.location.lower() in resume_location:
            location_rule_score = 10
        elif not job.location:
            location_rule_score = 5

        rule_total_score = max(
            0,
            min(100, role_rule_score + skill_rule_score + min(experience_rule_score, 20) + location_rule_score),
        )

        llm_result = self._score_with_llm(
            resume=resume,
            job=job,
            matched_skills=matched_skills,
            role_rule_score=role_rule_score,
            skill_rule_score=skill_rule_score,
            experience_rule_score=min(experience_rule_score, 20),
            location_rule_score=location_rule_score,
            rule_total_score=rule_total_score,
        )
        final_score = self._merge_scores(rule_total_score, llm_result)

        return JobMatchAnalysis(
            title=job.title,
            company=job.company,
            location=job.location,
            source_url=job.source_url,
            summary_text=job.summary_text,
            jd_text=job.jd_text,
            keywords=job.keywords,
            match_score=final_score,
            match_reason_short=llm_result["match_reason_short"],
            strengths=llm_result["strengths"],
            gaps=llm_result["gaps"],
        )

    def _score_with_llm(
        self,
        *,
        resume: ResumeDocument,
        job: ExtractedJobListing,
        matched_skills: list[str],
        role_rule_score: int,
        skill_rule_score: int,
        experience_rule_score: int,
        location_rule_score: int,
        rule_total_score: int,
    ) -> dict[str, object]:
        fallback = {
            "role_fit": self._normalize_dimension(role_rule_score, 40),
            "skill_fit": self._normalize_dimension(skill_rule_score, 30),
            "experience_fit": self._normalize_dimension(experience_rule_score, 20),
            "location_fit": self._normalize_dimension(location_rule_score, 10),
            "overall_score": rule_total_score,
            "match_reason_short": self._fallback_reason(rule_total_score, matched_skills, job),
            "strengths": matched_skills[:3] or ["有一定技术基础"],
            "gaps": ["需要结合岗位正文继续补充亮点"] if rule_total_score < 75 else ["可以进一步强调更贴近业务的成果"],
        }
        profile_json = json.dumps(resume.parsed_profile.model_dump(mode="json"), ensure_ascii=False)
        payload = self.chat_model.json_complete(
            system_prompt=(
                "You are a job matching evaluator. "
                "Return JSON only with these fields: "
                "role_fit, skill_fit, experience_fit, location_fit, overall_score, "
                "match_reason_short, strengths, gaps. "
                "All score fields must be integers from 0 to 100. "
                "Answer in Chinese. Keep match_reason_short under 60 Chinese characters. "
                "strengths and gaps must each be short string arrays with at most 3 items."
            ),
            user_prompt=(
                f"Resume profile JSON:\n{profile_json}\n\n"
                f"Job title: {job.title}\n"
                f"Job company: {job.company}\n"
                f"Job location: {job.location}\n"
                f"Matched skill keywords: {matched_skills}\n"
                f"Rule role score (0-40): {role_rule_score}\n"
                f"Rule skill score (0-30): {skill_rule_score}\n"
                f"Rule experience score (0-20): {experience_rule_score}\n"
                f"Rule location score (0-10): {location_rule_score}\n"
                f"Rule total score (0-100): {rule_total_score}\n"
                f"Job summary:\n{job.summary_text}\n\n"
                f"Job content excerpt:\n{job.jd_text[:5000]}"
            ),
            fallback=fallback,
            run_name="job_match_llm_score",
        )
        result = {
            "role_fit": self._ensure_score(payload.get("role_fit"), fallback["role_fit"]),
            "skill_fit": self._ensure_score(payload.get("skill_fit"), fallback["skill_fit"]),
            "experience_fit": self._ensure_score(payload.get("experience_fit"), fallback["experience_fit"]),
            "location_fit": self._ensure_score(payload.get("location_fit"), fallback["location_fit"]),
            "overall_score": self._ensure_score(payload.get("overall_score"), fallback["overall_score"]),
            "match_reason_short": self._ensure_text(payload.get("match_reason_short"), fallback["match_reason_short"]),
            "strengths": self._ensure_list(payload.get("strengths"), fallback["strengths"]),
            "gaps": self._ensure_list(payload.get("gaps"), fallback["gaps"]),
        }
        return result

    def _merge_scores(self, rule_total_score: int, llm_result: dict[str, object]) -> int:
        role_fit = self._ensure_score(llm_result.get("role_fit"), 0)
        skill_fit = self._ensure_score(llm_result.get("skill_fit"), 0)
        experience_fit = self._ensure_score(llm_result.get("experience_fit"), 0)
        location_fit = self._ensure_score(llm_result.get("location_fit"), 0)
        llm_overall_score = self._ensure_score(llm_result.get("overall_score"), rule_total_score)

        weighted_score = round(
            role_fit * self.ROLE_WEIGHT
            + skill_fit * self.SKILL_WEIGHT
            + experience_fit * self.EXPERIENCE_WEIGHT
            + location_fit * self.LOCATION_WEIGHT
        )
        final_score = weighted_score
        if abs(llm_overall_score - weighted_score) <= self.OVERALL_SCORE_DRIFT_LIMIT:
            final_score = round((weighted_score * 0.8) + (llm_overall_score * 0.2))
        return max(0, min(100, final_score))

    def _normalize_dimension(self, value: int, max_value: int) -> int:
        if max_value <= 0:
            return 0
        return max(0, min(100, round((value / max_value) * 100)))

    def _ensure_score(self, value: object, default: int) -> int:
        try:
            score = int(value)
        except (TypeError, ValueError):
            score = int(default)
        return max(0, min(100, score))

    def _ensure_text(self, value: object, default: str) -> str:
        if not isinstance(value, str):
            return default
        text = value.strip()
        return text or default

    def _ensure_list(self, value: object, default: list[str]) -> list[str]:
        if not isinstance(value, list):
            return default
        result = [str(item).strip() for item in value if str(item).strip()]
        return result[:3] or default

    def _fallback_reason(self, score: int, matched_skills: list[str], job: ExtractedJobListing) -> str:
        if score >= 80:
            return f"你的经历与 {job.title} 的核心要求较贴合，适合优先关注。"
        if score >= 60:
            return f"你和 {job.title} 有部分技能重合，适合优化简历后尝试。"
        if matched_skills:
            return f"{job.title} 与你有一定技能交集，但整体仍有差距。"
        return f"{job.title} 与当前简历存在一定差距，可作为补充投递方向。"

    def _split_terms(self, value: str) -> list[str]:
        if not value:
            return []
        return [item for item in re.split(r"[\s/,_-]+", value.lower()) if item]
