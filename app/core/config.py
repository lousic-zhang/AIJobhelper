from __future__ import annotations

import os
import shlex
from pathlib import Path
from functools import lru_cache

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


class Settings:
    def __init__(self) -> None:
        self.app_name = "AIJobHelper"
        self.mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.mongodb_db = os.getenv("MONGODB_DB", "aijobhelper")
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.session_ttl_seconds = int(os.getenv("SESSION_TTL_SECONDS", "86400"))
        self.session_cookie_name = os.getenv("SESSION_COOKIE_NAME", "aijobhelper_session")
        self.elasticsearch_url = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
        self.elasticsearch_index_prefix = os.getenv("ELASTICSEARCH_INDEX_PREFIX", "aijobhelper")
        self.mcp_browser_fetch_url = os.getenv("MCP_BROWSER_FETCH_URL", "")
        self.browser_mcp_enabled = os.getenv("BROWSER_MCP_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
        self.browser_mcp_command = os.getenv("BROWSER_MCP_COMMAND", "npx")
        self.browser_mcp_args = self._parse_command_args(
            os.getenv("BROWSER_MCP_ARGS", "-y @playwright/mcp"),
        )
        self.browser_mcp_proxy_url = os.getenv("BROWSER_MCP_PROXY_URL", "")
        self.browser_mcp_timeout_seconds = float(os.getenv("BROWSER_MCP_TIMEOUT_SECONDS", "90"))
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.openai_proxy_url = os.getenv("OPENAI_PROXY_URL", "")
        self.upload_dir = os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads"))
        self.default_user_id = os.getenv("DEFAULT_USER_ID", "local-user")
        self.default_chat_id = os.getenv("DEFAULT_CHAT_ID", "job-chat")
        self.job_match_max_depth = int(os.getenv("JOB_MATCH_MAX_DEPTH", "1"))
        self.job_match_max_breadth = int(os.getenv("JOB_MATCH_MAX_BREADTH", "8"))
        self.job_match_max_pages = int(os.getenv("JOB_MATCH_MAX_PAGES", "20"))
        self.job_match_max_results = int(os.getenv("JOB_MATCH_MAX_RESULTS", "10"))

    def _parse_command_args(self, raw: str) -> list[str]:
        text = str(raw or "").strip()
        if not text:
            return []
        try:
            return shlex.split(text, posix=False)
        except ValueError:
            return text.split()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
