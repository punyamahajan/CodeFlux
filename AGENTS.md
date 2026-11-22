# AGENTS.md

## Project
OmniKey (package `codeflux`) is a unified AI gateway: admins pool provider keys and issue limited platform keys; requests are routed with fallback; every decision and number is explained. Full plan: docs/PLAN.md. Prototype scope, free hosting, not production grade.

## Commands
- Install: `pip install -r requirements.txt -r requirements-dev.txt` and `cd frontend && npm ci`
- Backend dev: `uvicorn codeflux.app:app --reload --port 8000`
- Frontend dev: `cd frontend && npm run dev` (proxies /api and /v1 to :8000)
- Migrate: `alembic upgrade head`; new migration: `alembic revision --autogenerate -m message`
- Lint: `ruff check .` and `ruff format --check .`
- Test: `pytest -q` (needs DATABASE_URL pointing at a throwaway Postgres)
- Frontend checks: `npm run lint && npm run typecheck && npm test -- --run && npm run build`
- Seed: `python -m scripts.seed`
- Full validation = every command above, all green, before any commit.

## Code rules
- Python 3.12, type hints everywhere, async I/O only, no print (use the logger).
- Routers stay thin; logic lives in services. Providers never touch the database. Explain code only reads stored facts.
- Settings come only from `codeflux/settings.py`; never read os.environ elsewhere.
- Money is integer micro-USD (BigInteger). Times are UTC. IDs are prefixed random strings (org_, key_, trc_).
- Errors: `/v1` uses the OpenAI error envelope; `/api` returns {error: {code, message}}.
- Lists take `limit` and `cursor`.

## Security rules
- Provider keys: Fernet encrypted, only the last 4 characters returned.
- Platform keys: ok_live_ prefix, HMAC-SHA256 digest stored, plaintext returned once.
- Never log or return secrets, Authorization headers or prompt text. Prompt and reply text are not stored in traces unless STORE_PAYLOADS=true.
- Every tenant query filters by org_id. Members only read their own records.
- Never commit .env or real keys.

## Explain contract
- Each feature writes a facts JSON validated by a Pydantic model in `codeflux/explain/facts.py`, with a schema_version field.
- Explanations come from deterministic templates in `explain/templates.py`.
- AI narration receives facts only and may not add numbers; any reply with a number missing from the facts is discarded.

## Testing rules
- Postgres in tests, not SQLite. Mock providers with respx. No real network or keys.
- Every bug fix gets a regression test.
- Never skip, loosen or delete a failing test.

## Git and CI
- Work on branch omnikey-v2, commit as `stage-N: summary`, push, wait for CI green.
- main deploys to Render only after CI passes.

## Gotchas
- Neon: use the direct (non-pooled) connection string. Create the engine with pool_pre_ping=True, because Neon pauses idle databases and drops old connections.
- Alembic reads DATABASE_URL from settings, never from alembic.ini.
- Neon URLs: convert `postgresql://` to `postgresql+asyncpg://` and replace `sslmode=require` with `ssl=require`, which asyncpg expects.
- Run one uvicorn worker. In-memory state resets on restart and must never corrupt data.
- Render's free filesystem is ephemeral: write no files at runtime.
- Streaming: fall back only before the first byte; always close upstream responses.
- The final streaming chunk can have an empty `choices` list.
- Gemini keys arrive in the x-goog-api-key header.

## Definition of done for a stage
All steps implemented, tests written, full validation green, gate checks passed, committed, CI green, report delivered.