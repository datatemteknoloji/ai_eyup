# CLAUDE.md — datatem AI / Server Management Platform

## Project Overview

Full-stack server management platform: React/Vite frontend + FastAPI/Python backend, PostgreSQL (TimescaleDB), Redis, Ollama AI, Prometheus. Deployed via Docker Compose.

## Architecture

- **Frontend:** `frontend/` — React 18 + Vite + TailwindCSS + TanStack Query
- **Backend:** `backend/app/` — FastAPI + SQLAlchemy + Alembic (volume-mounted into container)
- **Services:** TimescaleDB, Redis, Prometheus, Ollama, Pushgateway

## Running the App

```bash
docker compose up -d          # start all services
docker compose build          # rebuild after Dockerfile changes (not needed for Python/TS source changes)
docker compose logs -f backend  # tail backend logs
```

The backend source is volume-mounted (`./backend/app:/app/app`), so Python changes are live immediately (uvicorn auto-reloads). Frontend changes require a `docker compose build` + `up -d` to rebuild the nginx image.

## Testing

Run command:
- **Backend:** `docker exec -e PYTHONPATH=/app -w /app server_management_backend python3 -m pytest app/tests/ -v`
- **Frontend:** `docker run --rm -v $(pwd)/frontend:/app -w /app node:20-alpine sh -c "npm install --legacy-peer-deps && npm test"`

Test directories:
- Backend: `backend/app/tests/`
- Frontend: `frontend/src/test/`

See [TESTING.md](TESTING.md) for full documentation.

### Test expectations

- 100% test coverage is the goal — tests make vibe coding safe
- When writing new functions, write a corresponding test
- When fixing a bug, write a regression test
- When adding error handling, write a test that triggers the error
- When adding a conditional (if/else, switch), write tests for BOTH paths
- Never commit code that makes existing tests fail

## Key Security Decisions (June 2026)

- JWT tokens have 60-minute TTL + jti-based blacklist on logout
- All destructive endpoints require `require_role("operator")`
- Sudo passwords sent via stdin PTY — never in command strings
- Hypervisor API responses strip raw passwords (return `has_password: bool` only)
- WebSocket terminal requires JWT token via `?token=` query param
- Package file uploads are sanitized and path-traversal-checked

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
