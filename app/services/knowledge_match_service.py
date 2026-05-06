from __future__ import annotations

import json

from app.core.llm import ChatModel
from app.services.knowledge_retrieval_service import KnowledgeRetrievalService
from app.services.resume_service import ResumeService


class KnowledgeMatchService:
    def __init__(
        self,
        *,
        chat_model: ChatModel,
        resume_service: ResumeService,
        retrieval_service: KnowledgeRetrievalService,
    ) -> None:
        self.chat_model = chat_model
        self.resume_service = resume_service
        self.retrieval_service = retrieval_service

    def match_resume_to_base(self, *, user_id: str, knowledge_base_id: str) -> str:
        resume = self.resume_service.get_current_resume(user_id)
        if resume is None:
            return "你还没有上传简历。请先去个人简历或主聊天页上传简历，我再帮你做当前岗位知识库的匹配分析。"

        chunks = self.retrieval_service.sample_chunks(knowledge_base_id=knowledge_base_id, limit=6)
        if not chunks:
            return "当前知识库还没有可检索内容。请先导入岗位链接，再进行匹配分析。"

        knowledge_context = "\n\n".join(
            f"[来源] {chunk.source_url}\n[标题] {chunk.title}\n[内容]\n{chunk.content}"
            for chunk in chunks
        )
        resume_json = json.dumps(resume.parsed_profile.model_dump(mode="json"), ensure_ascii=False)
        system_prompt = (
            "你是求职岗位匹配分析助手。"
            "请基于当前简历和岗位知识库内容，输出中文分析，必须包含：总体匹配结论、主要优势、明显缺口、简历补强建议、面试准备建议。"
            "不要编造岗位要求，也不要输出与当前知识库无关的建议。"
        )
        user_prompt = (
            f"当前简历结构化信息：\n{resume_json}\n\n"
            f"当前岗位知识库内容：\n{knowledge_context}"
        )
        return self.chat_model.complete(system_prompt=system_prompt, user_prompt=user_prompt)

