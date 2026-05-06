from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ResumeEducation(BaseModel):
    school: str = ""
    degree: str = ""
    major: str = ""
    duration: str = ""


class ResumeProject(BaseModel):
    name: str = ""
    description: str = ""
    role: str = ""
    duration: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)


class ResumeInternship(BaseModel):
    company: str = ""
    role: str = ""
    duration: str = ""
    summary: str = ""
    highlights: list[str] = Field(default_factory=list)


class ResumeContact(BaseModel):
    phone: str = ""
    email: str = ""
    location: str = ""
    github: str = ""
    blog: str = ""


class ResumeProfile(BaseModel):
    name: str = ""
    target_role: str = ""
    school: str = ""
    highest_degree: str = ""
    summary: str = ""
    contact: ResumeContact = Field(default_factory=ResumeContact)
    education: list[ResumeEducation] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    projects: list[ResumeProject] = Field(default_factory=list)
    internships: list[ResumeInternship] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    awards: list[str] = Field(default_factory=list)


class ResumeDocument(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    file_name: str
    file_path: str
    uploaded_at: datetime
    raw_text: str
    parsed_profile: ResumeProfile
    source: str = "chat_upload"

    model_config = {"populate_by_name": True}
