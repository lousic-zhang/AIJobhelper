from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.llm import ChatModel
from app.models.resume import ResumeDocument, ResumeProfile

try:
    from langchain_community.document_loaders import PyPDFLoader
except ImportError:  # pragma: no cover
    PyPDFLoader = None


class ResumeService:
    def __init__(self, database: Any, chat_model: ChatModel) -> None:
        self.collection = database["resumes"]
        self.chat_model = chat_model

    def get_current_resume(self, user_id: str) -> ResumeDocument | None:
        document = self.collection.find_one({"user_id": user_id})
        if not document:
            return None
        document["_id"] = str(document["_id"])
        return ResumeDocument.model_validate(document)

    def parse_and_save(self, user_id: str, file_path: str, file_name: str) -> ResumeDocument:
        raw_text = self._extract_text(file_path)
        parsed_profile = self._parse_profile(raw_text)
        now = datetime.utcnow()
        document = {
            "_id": user_id,
            "user_id": user_id,
            "file_name": file_name,
            "file_path": file_path,
            "uploaded_at": now,
            "raw_text": raw_text,
            "parsed_profile": parsed_profile.model_dump(mode="json"),
            "source": "chat_upload",
        }
        self.collection.replace_one({"user_id": user_id}, document, upsert=True)
        saved = self.collection.find_one({"user_id": user_id})
        saved["_id"] = str(saved["_id"])
        return ResumeDocument.model_validate(saved)

    def _extract_text(self, file_path: str) -> str:
        path = Path(file_path)
        if not path.exists():
            raise ValueError(f"Resume file does not exist: {file_path}")
        if PyPDFLoader is None:
            raise RuntimeError("LangChain PDF loader is unavailable. Install langchain-community and pypdf.")

        loader = PyPDFLoader(str(path))
        documents = loader.load()
        text = "\n\n".join(doc.page_content for doc in documents if doc.page_content).strip()
        if not text:
            raise RuntimeError("Resume parsing failed because no text was extracted.")
        return text

    def _parse_profile(self, raw_text: str) -> ResumeProfile:
        system_prompt = (
            "You are the resume parser inside an AI job assistant. "
            "Extract as much structured information as possible from the resume text and return JSON only. "
            "Fields: name, target_role, school, highest_degree, summary, contact, education, skills, "
            "projects, internships, highlights, certifications, awards. "
            "contact is an object with phone, email, location, github, blog. "
            "education is an array with school, degree, major, duration. "
            "projects is an array with name, description, role, duration, tech_stack, highlights. "
            "internships is an array with company, role, duration, summary, highlights. "
            "If a field does not exist, return an empty string, empty object, or empty array. Do not omit fields."
        )
        fallback = self._fallback_profile(raw_text)
        try:
            payload = self.chat_model.json_complete(
                system_prompt=system_prompt,
                user_prompt=raw_text[:16000],
                fallback=fallback,
            )
        except Exception:
            payload = fallback
        normalized = self._normalize_payload(payload, fallback)
        return ResumeProfile.model_validate(normalized)

    def _normalize_payload(self, payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        data = dict(fallback)
        if isinstance(payload, dict):
            data.update(payload)

        if isinstance(data.get("contact"), str):
            data["contact"] = {
                "phone": "",
                "email": "",
                "location": data["contact"],
                "github": "",
                "blog": "",
            }
        elif not isinstance(data.get("contact"), dict):
            data["contact"] = dict(fallback["contact"])

        data["skills"] = self._ensure_str_list(data.get("skills"))
        data["highlights"] = self._ensure_str_list(data.get("highlights"))
        data["certifications"] = self._ensure_str_list(data.get("certifications"))
        data["awards"] = self._ensure_str_list(data.get("awards"))

        data["education"] = self._normalize_education(data.get("education"))
        data["projects"] = self._normalize_projects(data.get("projects"))
        data["internships"] = self._normalize_internships(data.get("internships"))

        if not data.get("school") and data["education"]:
            data["school"] = data["education"][0].get("school", "")
        if not data.get("highest_degree") and data["education"]:
            data["highest_degree"] = data["education"][0].get("degree", "")

        for key in ("name", "target_role", "school", "highest_degree", "summary"):
            value = data.get(key, "")
            data[key] = value if isinstance(value, str) else str(value)

        return data

    def _normalize_education(self, value: Any) -> list[dict[str, str]]:
        if isinstance(value, str):
            return [{"school": value, "degree": "", "major": "", "duration": ""}] if value.strip() else []
        if not isinstance(value, list):
            return []
        result: list[dict[str, str]] = []
        for item in value:
            if isinstance(item, str):
                result.append({"school": item, "degree": "", "major": "", "duration": ""})
                continue
            if isinstance(item, dict):
                result.append(
                    {
                        "school": self._string(item.get("school")),
                        "degree": self._string(item.get("degree")),
                        "major": self._string(item.get("major")),
                        "duration": self._string(item.get("duration") or item.get("time")),
                    }
                )
        return result

    def _normalize_projects(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, str):
                result.append(
                    {
                        "name": item,
                        "description": "",
                        "role": "",
                        "duration": "",
                        "tech_stack": [],
                        "highlights": [],
                    }
                )
                continue
            if isinstance(item, dict):
                result.append(
                    {
                        "name": self._string(item.get("name")),
                        "description": self._string(item.get("description")),
                        "role": self._string(item.get("role")),
                        "duration": self._string(item.get("duration") or item.get("time")),
                        "tech_stack": self._ensure_str_list(item.get("tech_stack") or item.get("skills")),
                        "highlights": self._ensure_str_list(item.get("highlights")),
                    }
                )
        return result

    def _normalize_internships(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, str):
                result.append(
                    {
                        "company": item,
                        "role": "",
                        "duration": "",
                        "summary": "",
                        "highlights": [],
                    }
                )
                continue
            if isinstance(item, dict):
                result.append(
                    {
                        "company": self._string(item.get("company")),
                        "role": self._string(item.get("role")),
                        "duration": self._string(item.get("duration") or item.get("time")),
                        "summary": self._string(item.get("summary") or item.get("description")),
                        "highlights": self._ensure_str_list(item.get("highlights")),
                    }
                )
        return result

    def _ensure_str_list(self, value: Any) -> list[str]:
        if isinstance(value, str):
            return [value] if value.strip() else []
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
            elif item is not None:
                text = str(item).strip()
                if text:
                    result.append(text)
        return result

    def _string(self, value: Any) -> str:
        if value is None:
            return ""
        return value if isinstance(value, str) else str(value)

    def _fallback_profile(self, raw_text: str) -> dict[str, Any]:
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        name = lines[0] if lines else "Unknown"
        skills: list[str] = []
        for keyword in ("Go", "Golang", "Python", "MySQL", "Redis", "Docker", "LangChain", "MongoDB", "FastAPI"):
            if keyword.lower() in raw_text.lower():
                skills.append(keyword)

        return {
            "name": name[:30],
            "target_role": "Backend Intern",
            "school": "",
            "highest_degree": "",
            "summary": "",
            "contact": {
                "phone": "",
                "email": "",
                "location": "",
                "github": "",
                "blog": "",
            },
            "education": [],
            "skills": skills,
            "projects": [
                {
                    "name": "Project extracted from resume text",
                    "description": "The model is unavailable or structured parsing fell back to a placeholder result.",
                    "role": "",
                    "duration": "",
                    "tech_stack": [],
                    "highlights": [],
                }
            ],
            "internships": [],
            "highlights": ["The raw resume text was extracted successfully. A richer structured result is available when the model is reachable."],
            "certifications": [],
            "awards": [],
        }
