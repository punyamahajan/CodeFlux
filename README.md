# OmniKey (codeflux)

OmniKey is a unified AI gateway for teams. Admins pool provider keys (OpenAI, Gemini, Groq, OpenRouter, Mistral, Ollama) and issue limited platform keys (`ok_live_...`) to teammates with credit limits, rate limits, allowed routes, and expiry.

The gateway routes each request across providers with automatic fallback, keeps conversation context across provider switches through sessions, and records structured facts about every decision and cost. An Explain layer turns those facts into plain-language answers explaining why decisions were made.

## Architecture

- **Backend**: FastAPI gateway, Pydantic v2, SQLAlchemy 2 async with asyncpg on Neon Postgres, Alembic, httpx.
- **Frontend**: React 18, Vite, Tailwind CSS (served by FastAPI in production).
- **Hosting & CI**: Docker on Render, GitHub Actions CI.

## Development

- Install: `pip install -r requirements.txt -r requirements-dev.txt`
- Backend dev: `uvicorn codeflux.app:app --reload --port 8000`
- Lint: `ruff check . && ruff format --check .`
- Test: `pytest -q`
