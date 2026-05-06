# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AIJobHelper is a local job-search assistant built with FastAPI + Jinja + LangChain. It helps users manage resumes, track job applications, build knowledge bases per job target, and match resumes against job listings.

## Commands

```bash
# Install dependencies
python -m pip install -r requirements.txt

# Run development server
python -m uvicorn app.main:app --host 127.0.0.1 --port 8011

# Run tests
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_callbacks.py -v
```

## Architecture

### Core Pattern: Router -> Handler -> Tool

The chat system follows a three-stage processing pattern:

1. **Router** (`app/chat/router.py`): Classifies user messages and routes to the appropriate handler. Returns `RouteDecision` with handler name and rewritten input.

2. **Handlers** (`app/chat/handlers.py`): Domain-specific processors that orchestrate tools and LLM calls:
   - `ResumeHandlerAgent` - resume parsing, summaries, questions
   - `ApplicationHandlerAgent` - job application CRUD
   - `KnowledgeHandlerAgent` - knowledge base creation, URL ingestion, RAG Q&A
   - `JobMatchListHandlerAgent` - batch job URL matching via Browser MCP
   - `DefaultHandler` - general career advice fallback

3. **Tools** (`app/chat/tools.py`): Stateless functions wrapped as LangChain tools. Each tool performs a single operation (e.g., `ApplicationAddTool`, `KnowledgeIngestFromUrlTool`).

### Agents

Two main agents orchestrate the system:

- **JobChatAgent** (`app/chat/agent.py`): Main chat entrypoint. Uses `JobRouter` for routing, maintains multi-turn memory via `Memoryx`, and delegates to handlers.
- **KnowledgeChatAgent**: Dedicated agent for knowledge-base-specific chat, always routes to `KnowledgeHandlerAgent`.

### Memory System

`pkg/memoryx.py` + `pkg/summarybuffer.py` implement a LangChain-compatible memory layer:
- Per-chat/thread memory isolation using `{user_id}:{chat_id}` keys
- Summary-based buffer with LLM summarization when exceeding token limits
- Hybrid memory: persistent messages in MongoDB + runtime summaries

### Service Layer

Services in `app/services/` encapsulate business logic:
- `ResumeService` - PDF parsing, profile storage
- `ApplicationService` - application tracking CRUD
- `KnowledgeBaseService` - knowledge base management
- `KnowledgeIngestService` - URL ingestion with HTTP-first, Browser MCP fallback
- `KnowledgeRetrievalService` - Elasticsearch-based RAG retrieval
- `BrowserMCPService` - Playwright MCP integration for JS-rendered pages

### Infrastructure

- **Config**: `app/core/config.py` loads from `.env` via pydantic-style Settings class
- **LLM**: `app/core/llm.py` wraps LangChain ChatOpenAI with OpenAI-compatible endpoints
- **Database**: `app/core/db.py` MongoDB connection
- **Session**: `app/core/session.py` Redis-backed login sessions

## Key Data Flows

### Knowledge Base Ingestion
1. User submits URL in a knowledge base
2. `KnowledgeIngestService.ingest_url()` tries HTTP fetch first
3. If page appears empty/JS-only, falls back to `BrowserMCPService`
4. Content is cleaned, chunked, and indexed to Elasticsearch
5. Chat history stored in MongoDB for conversation continuity

### Job Match Flow
1. User pastes multiple job detail URLs
2. `JobMatchListHandlerAgent` creates a task via `JobMatchTaskService`
3. Each URL opened via Playwright MCP, text extracted
4. `JobMatchService` scores each job against current resume
5. Results stored and viewable at `/job-matches`

## Required Services

- MongoDB (document storage)
- Redis (session storage)
- Elasticsearch (knowledge base indexing)
- OpenAI-compatible LLM endpoint

## Environment Variables

Key settings in `.env`:
- `MONGODB_URI`, `MONGODB_DB` - MongoDB connection
- `REDIS_URL`, `SESSION_TTL_SECONDS` - Redis session config
- `ELASTICSEARCH_URL`, `ELASTICSEARCH_INDEX_PREFIX` - search indexing
- `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` - LLM config
- `BROWSER_MCP_ENABLED`, `BROWSER_MCP_COMMAND`, `BROWSER_MCP_ARGS` - Playwright MCP
- `UPLOAD_DIR` - resume file storage

## Code Conventions

- Handlers return `ChatResponse` with `reply`, `handler`, `tool`, and `debug` fields
- Tools are dataclasses with `name`, `description`, and `call()` method
- Fallback logic is explicit: every LLM call has a `fallback` parameter for graceful degradation
- Chinese responses expected for user-facing chat; system prompts in English
