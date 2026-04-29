# Job Application Agent

An autonomous AI agent that reads your resume, researches a company, and produces a tailored job application package — all driven by Claude's tool use API.

## What it does

Paste any job description. The agent autonomously:

1. **Reads your resume** from a Markdown file on disk
2. **Searches the web** for company culture, tech stack, and recent news (2–3 targeted DuckDuckGo queries)
3. **Analyzes the match** — keyword hits, skill gaps, and a 0–100 match score
4. **Rewrites 3–5 resume bullets** to emphasize relevant experience (no fabrication)
5. **Drafts a cover letter** tailored to the company and role
6. **Saves everything to PostgreSQL** — full history with the agent execution trace
7. **Returns a structured report** visible in the React UI across four tabs

---

## Agent architecture

```
User submits JD
      │
      ▼
FastAPI route → run_agent()
      │
      ▼
┌─────────────────────────────────────────┐
│           Manual agentic loop           │
│                                         │
│  POST /v1/messages (claude-opus-4-7)   │
│    • adaptive thinking enabled          │
│    • 3 tools provided                   │
│    • system + tools prefix cached       │
│         │                               │
│         ▼                               │
│    stop_reason == "tool_use"?           │
│         │                               │
│    ┌────┴────────────────────┐          │
│    │  execute_tool()         │          │
│    │  ├─ read_resume         │          │
│    │  ├─ search_web          │          │
│    │  └─ save_application    │          │
│    └────────────────────────┘          │
│         │                               │
│    Append tool_results, repeat          │
│         │                               │
│    stop_reason == "end_turn"  ──────────┤
└─────────────────────────────────────────┘
      │
      ▼
AgentResult → HTTP response → React UI
```

### Why manual loop vs. the SDK tool runner

The manual loop gives explicit control over:
- **Logging**: every iteration is captured as a typed `AgentStep` (tool_call / tool_result / thought) and stored in PostgreSQL — the UI's Agent Trace tab replays the exact execution
- **Context propagation**: the `context` dict threads state (resume text, DB session, user_id) across all tool calls without globals
- **Commit timing**: `save_application` calls `db.flush()` (not commit), and the HTTP route's dependency handles commit/rollback atomically

### Prompt caching

Two `cache_control: {type: "ephemeral"}` markers are placed on stable content:
- The **system prompt** block
- The **last tool definition** (which caches the full tools prefix)

Because both are identical across every iteration of the loop, turns 2–N hit the cache — reducing latency from ~4s to ~1s per iteration and cutting input token costs by ~90%.

### Tools

| Tool | Purpose | Implementation |
|---|---|---|
| `read_resume` | Reads `resumes/{user_id}.md` from disk | Sync file I/O, falls back to `default.md` |
| `search_web` | DuckDuckGo search, returns top N results | `DDGS` in `run_in_executor` (async-safe) |
| `save_application` | Persists full analysis to PostgreSQL | SQLAlchemy async, JSONB for structured fields |

---

## Stack

| Layer | Technology |
|---|---|
| LLM | Claude claude-opus-4-7 (Anthropic) |
| Backend | Python 3.12, FastAPI, SQLAlchemy async |
| Database | PostgreSQL 16, asyncpg driver |
| Web search | duckduckgo-search (no API key needed) |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS |
| Deployment | Docker Compose |

---

## Quick start

### Prerequisites
- Docker + Docker Compose
- An Anthropic API key

### 1. Clone and configure

```bash
git clone <repo-url>
cd job-agent
cp backend/.env.example backend/.env
# Edit backend/.env — set ANTHROPIC_API_KEY
```

### 2. Add your resume

```bash
# Edit the sample or replace with your own:
nano backend/resumes/default.md
```

The file should be plain Markdown — work experience, skills, education. The agent reads it as-is.

### 3. Run with Docker Compose

```bash
docker compose up --build
```

Open **http://localhost:5173** — paste a job description and click **Run Agent**.

The first run takes 30–60 seconds (the agent makes multiple API calls). Subsequent analyses appear in the sidebar.

---

## Local development (without Docker)

```bash
# Terminal 1 — PostgreSQL
docker compose up db

# Terminal 2 — Backend
cd backend
pip install -r requirements.txt
cp .env.example .env   # set ANTHROPIC_API_KEY and DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/jobagent
uvicorn app.main:app --reload

# Terminal 3 — Frontend
cd frontend
npm install
npm run dev
```

Frontend dev server proxies `/api` to `localhost:8000` via Vite config, so no CORS issues.

---

## Project structure

```
job-agent/
├── backend/
│   ├── app/
│   │   ├── agent/
│   │   │   ├── agent.py      # agentic loop
│   │   │   ├── tools.py      # tool definitions + handlers
│   │   │   └── prompts.py    # system prompt
│   │   ├── api/
│   │   │   └── routes.py     # FastAPI endpoints
│   │   ├── core/
│   │   │   └── config.py     # pydantic settings
│   │   └── db/
│   │       ├── models.py     # SQLAlchemy ORM
│   │       ├── database.py   # async engine + session
│   │       └── schemas.py    # pydantic API schemas
│   ├── resumes/
│   │   └── default.md        # sample resume
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.tsx            # main layout + history sidebar
│       ├── components/
│       │   ├── JobForm.tsx    # JD input + submit
│       │   ├── ResultPanel.tsx # tabbed results
│       │   └── AgentSteps.tsx # agent trace display
│       ├── api/client.ts      # typed API wrapper
│       └── types/index.ts     # shared TypeScript types
└── docker-compose.yml
```

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/analyze` | Run the agent on a job description |
| GET | `/api/applications?user_id=` | List past applications |
| GET | `/api/applications/{id}` | Full application detail |
| GET | `/api/resume/{user_id}` | Read resume content |
| POST | `/api/resume/{user_id}` | Update resume content |

---

## Key design decisions

**No Alembic** — `Base.metadata.create_all` runs on startup. Simple enough for a portfolio project; swap in Alembic for production.

**JSONB columns** — `skill_gaps`, `keyword_matches`, `rewritten_bullets`, and `agent_steps` are stored as JSONB so schema can evolve without migrations.

**DuckDuckGo over SerpAPI/Brave** — zero API key friction for demos. Swap `tool_search_web` in `tools.py` to use any search provider.

**Adaptive thinking** — `thinking: {type: "adaptive"}` lets Claude decide when to reason deeply vs. respond directly, which works better than a fixed budget for the diverse sub-tasks in this agent.
