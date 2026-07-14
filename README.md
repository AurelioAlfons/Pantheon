# Pantheon

Building a multi-agent AI system with a shared task queue and a Digimon World Championship-inspired 2D dashboard. Six specialized agents (project manager, developer, researcher, QA, comms, overseer) pass work to each other through Postgres, no message bus involved. The backend is FastAPI, the database is Supabase, and scheduling runs on APScheduler polling a task-status table. No orchestration frameworks, no Redis, no Celery. That's a deliberate choice, not a gap.

## Structure

- `backend/` — FastAPI app (Python 3.11, venv + `requirements.txt`)
- `frontend/` — React + TypeScript + Vite app, thin client only, no business logic
- `agents/` — Markdown agent configs (YAML frontmatter + system prompt), loaded at runtime. See `agents/README.md` for the pattern.

## Running locally

### Backend

```
cd backend
venv\Scripts\activate
uvicorn app.main:app --reload
```

Health check: `GET http://localhost:8000/health`

### Frontend

```
cd frontend
npm run dev
```

## Environment

Copy `.env` at the repo root with:

```
MODE=demo   # or "personal"
```

I use `demo` mode for the public portfolio instance (mocked integrations, rate-limited, committed `agents/` templates) and `personal` mode for my own private instance behind auth, with real integrations and agent configs that live outside this repo.
