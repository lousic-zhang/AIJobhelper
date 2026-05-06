# AIJobHelper

AIJobHelper is a local job-search assistant built with `FastAPI + Jinja + LangChain`. 

The content as follow:


## Pages

- `/login` - login page
- `/register` - register page
- `/chat` - main job assistant
- `/resume` - current resume page
- `/applications` - application tracking page
- `/knowledge` - job knowledge-base page
- `/job-matches` - matched jobs list page

## Current capabilities

- Upload a PDF resume and parse it into structured data
- Review structured resume data on the resume page
- Create, query, and update application records
- Create multiple job knowledge bases, one per target role
- Import a job URL into a knowledge base
- Query a specific knowledge base with RAG-style retrieval
- Run current-resume vs current-job matching analysis
- Paste multiple job detail URLs and rank them against the current resume with Playwright MCP
- Protect all business pages and APIs with Redis-backed login sessions

## Knowledge-base flow

Each knowledge base belongs to one user and one job target.

URL ingestion works like this:

1. submit a URL inside a knowledge base
2. try normal HTTP fetch first
3. if the page looks empty or JS-only, fall back to Browser MCP
4. clean and chunk the content
5. index it into Elasticsearch
6. chat against that knowledge base only

Chat history for each knowledge base is stored in MongoDB, so reopening the page can continue prior conversations.

## Job match flow

The job match page now targets job detail URLs directly:

1. paste multiple job detail URLs, one per line
2. the app opens each page with Playwright MCP
3. extract the rendered page text
4. detect job title, location, keywords, and JD summary
5. score each job against the current resume
6. show ranked results with short matching reasons

## Requirements

At minimum, prepare these services:

- MongoDB
- Redis
- Elasticsearch
- an OpenAI-compatible LLM endpoint

Recommended browser support:

- Playwright MCP server

Optional backward-compatible fallback:

- a legacy browser fetch HTTP service exposed as `MCP_BROWSER_FETCH_URL`

## Setup

1. Enter the project directory

```powershell
cd D:\computer\Golang_Project\AIJobHelper
```

2. Install dependencies

```powershell
python -m pip install -r requirements.txt
```

3. Copy the environment template

```powershell
Copy-Item .env.example .env
```

4. Fill in `.env`

Important settings:

- `MONGODB_URI`
- `MONGODB_DB`
- `REDIS_URL`
- `SESSION_TTL_SECONDS`
- `ELASTICSEARCH_URL`
- `ELASTICSEARCH_INDEX_PREFIX`
- `BROWSER_MCP_ENABLED`
- `BROWSER_MCP_COMMAND`
- `BROWSER_MCP_ARGS`
- `BROWSER_MCP_PROXY_URL`
- `BROWSER_MCP_TIMEOUT_SECONDS`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `OPENAI_PROXY_URL`
- `UPLOAD_DIR`

Optional compatibility setting:

- `MCP_BROWSER_FETCH_URL`

5. Start the app

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8011
```

The app will start Playwright MCP through stdio when a Browser MCP task runs.

6. Open the app

- [http://127.0.0.1:8011/login](http://127.0.0.1:8011/login)

## Recommended `.env` example

```env
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=aijobhelper
REDIS_URL=redis://:yourpassword@127.0.0.1:6379/0
SESSION_TTL_SECONDS=604800
ELASTICSEARCH_URL=http://127.0.0.1:9200
ELASTICSEARCH_INDEX_PREFIX=aijobhelper
MCP_BROWSER_FETCH_URL=http://127.0.0.1:8787/browser/fetch
BROWSER_MCP_ENABLED=true
BROWSER_MCP_COMMAND=npx
BROWSER_MCP_ARGS=-y @playwright/mcp
BROWSER_MCP_PROXY_URL=
BROWSER_MCP_TIMEOUT_SECONDS=90
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=qwen3.5-flash
OPENAI_PROXY_URL=
UPLOAD_DIR=D:\computer\Golang_Project\AIJobHelper\uploads
DEFAULT_CHAT_ID=job-chat
JOB_MATCH_MAX_DEPTH=1
JOB_MATCH_MAX_BREADTH=8
JOB_MATCH_MAX_PAGES=20
JOB_MATCH_MAX_RESULTS=10
```

## Redis session notes

- session cookie name: `aijobhelper_session`
- Redis key format: `session:{session_id}`
- Redis must be reachable and correctly authenticated

If login fails with a Redis message, usually it means one of these:

1. Redis is not running
2. `REDIS_URL` is missing the password
3. `REDIS_URL` points to the wrong Redis instance

## Elasticsearch notes

Knowledge-base documents are isolated by `knowledge_base_id`.
Queries always filter by the selected knowledge base, so different job knowledge bases do not mix retrieval results.

If Elasticsearch is unavailable, the app currently falls back to an in-memory retrieval index for basic development use, but persistent knowledge retrieval works best with Elasticsearch running.
