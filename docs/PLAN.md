# OmniKey (CodeFlux): Blueprint and AI Agent Build Guide

A prototype built on the existing Python codebase: FastAPI gateway, React frontend, Neon Postgres, free hosting on Render with GitHub CI, and an Explain layer that answers why for every number and routing decision.

## Decision: continue in the existing repo

Continue on a new branch, omnikey-v2, in the current repository. Start fresh only if you change language.

My new-repo advice came from one constraint: Vercel cannot run a Python server or keep SQLite data, so hosting there meant rewriting the backend in TypeScript, which is effectively a new codebase. Render runs your Python app as it is, so that reason is gone.

Reasons to stay:

- The hard parts already work and have tests: OpenAI and Gemini normalization, streaming, provider adapters, the Fernet vault, HMAC client keys, the circuit breaker and key pooling.
- A rewrite spends your time on plumbing instead of the frontend and Explain layer, which are what make the project stand out.
- You keep the commit history, which shows how the project evolved.
- A long-lived process has no serverless duration limits for streams and debates, and lets the circuit breaker and rate limits stay in memory, so no Redis is needed.

Tag the current commit v1-streamlit before branching. Keep the package name codeflux; OmniKey is the product name in the UI. The system prompt, AGENTS.md and requirements below work for this path and would work unchanged for a fresh repo.

## Architecture decisions

| Concern | Choice | Reason |
| --- | --- | --- |
| Hosting | Render free web service, Docker runtime, one container serving the API and the built frontend | Deploys from GitHub on push; no CLI needed |
| CI/CD | GitHub Actions runs lint and tests; Render auto-deploys only after checks pass | A broken commit never goes live |
| Database | Neon free Postgres, SQLAlchemy 2 async with asyncpg, Alembic migrations | Render's free filesystem is wiped on every restart and its free Postgres expires after 30 days |
| Shared state | In process: circuit breaker, key cooldowns, rate limits; one worker | One instance, so no Redis; state resets on restart |
| Backend | FastAPI, Pydantic v2, httpx, the existing adapters and router | Reuse working code |
| Frontend | React 18, Vite, Tailwind, React Router, Recharts, built to frontend/dist and served by FastAPI | One deployable |
| Auth | Email and password (argon2), JWT in an httpOnly cookie | Enough for a demo |
| Provider keys | Fernet encrypted, master key in env, only the last 4 characters ever shown | Must be decryptable to call the provider |
| Platform keys | Prefix ok\_live\_, stored only as an HMAC-SHA256 digest, shown once | Never needed again after creation |
| Money | Integer micro-USD (1 USD = 1,000,000) | No float rounding errors |
| Gateway formats | OpenAI-compatible plus a non-streaming Gemini-format endpoint | Covers most SDKs |
| Background writes | FastAPI BackgroundTasks after the response | No queue needed |

Free-tier behavior to accept: the service sleeps after 15 minutes without traffic and takes about a minute to wake, and in-memory state resets then. Open the URL once before a demo, or add a free uptime pinger every 10 minutes (check the monthly free-hours limit). Verify current limits in the [Render free tier docs](https://render.com/docs/free).

## Explainable AI layer

Every number and decision is saved as structured facts at the moment it happens; explanations are generated from those facts, so they cannot contradict the data.

| Surface | Question it answers | Facts it reads |
| --- | --- | --- |
| Request trace | Why did this request go to this provider, model and key? | Route, strategy, attempts with outcome and reason |
| Cost | How was this cost calculated? | Tokens, price-table rows, price version |
| Credits | Why is my balance this amount? | Credit ledger entries |
| Per-user usage | Who consumed what, at what cost per 1K tokens? | Usage grouped by key and model |
| Blocked request | Why was I refused? | Limit checks: credits, RPM, expiry, allowed routes |
| Compare Arena | Why did model A rank above model B? | Latency, tokens, length, cost, judge scores and rubric |
| Debate Arena | Why did the judge pick this side? | Rounds, judge rubric scores, per-turn cost |

Rules:

1. Facts first: each feature stores its facts in a JSON column when it runs; nothing is reconstructed later.
2. Deterministic templates turn facts into an explanation object: headline, bullets and the raw facts.
3. An optional Explain with AI button sends only the facts JSON to a model. The prompt forbids adding or changing numbers, and the output is labeled AI-written.
4. One endpoint, GET /api/explain/\[kind\]/\[id\], serves every surface, and one WhyPanel component renders it everywhere in the UI.

## Repository structure

Stage 0 moves the existing modules into this layout with git mv. Save this document into the repo as docs/PLAN.md.

```text
repo-root/
├── AGENTS.md                  agent instructions (below)
├── docs/PLAN.md               this plan
├── DEMO.md                    five-minute demo script
├── Dockerfile                 multi-stage: build frontend, run FastAPI
├── render.yaml                Render blueprint
├── alembic.ini, alembic/      migrations
├── requirements.txt, requirements-dev.txt
├── .env.example
├── .github/workflows/ci.yml
├── codeflux/
│   ├── app.py                 create_app, routers, static frontend, /healthz
│   ├── settings.py            all configuration (pydantic-settings)
│   ├── db/                    session.py, models.py
│   ├── security/              crypto.py, passwords.py, tokens.py, redaction.py
│   ├── api/                   management API: auth, vault, keys, routes, requests, usage, traces, deps
│   ├── gateway/               api.py, auth.py, ratelimit.py, router.py, circuit.py,
│   │                          keypool.py, sessions.py, normalization.py, pii.py
│   ├── providers/             base.py, openai_compatible.py, gemini.py, registry.py
│   ├── metering/              pricing.py, ledger.py
│   ├── explain/               facts.py, templates.py, narrate.py, api.py
│   └── arenas/                compare.py, debate.py, judge.py, api.py
├── config/routes.yaml         default routes used by the seed
├── scripts/seed.py
├── tests/                     mirrors codeflux/ one to one
└── frontend/                  React + Vite + Tailwind (src/pages, components, api, auth)
```

## Master system prompt for the AI coding agent

Paste this as the agent's system prompt or custom instructions at the start of the project.

```text
You are the lead engineer building OmniKey (Python package name: codeflux), a unified AI gateway for teams.

PRODUCT
An admin plugs in provider API keys (OpenAI, Gemini, Groq, OpenRouter, Mistral, Ollama). The platform stores them encrypted. The admin then issues platform keys (prefix ok_live_) to teammates, each with a credit limit in USD, a requests-per-minute limit, allowed routes and an expiry. A teammate changes only base_url and api_key in their app and every model works through that one key. The gateway routes each request across providers with automatic, custom and task-specific fallback, keeps conversation context across provider switches through sessions, and records structured facts about everything it does. An Explain layer turns those facts into plain-language answers to why: why a request went to a provider, how a cost or credit balance was computed, why a request was blocked, why one model beat another in the Compare Arena, and why a side won the Debate Arena. Members get a portal and can request more limit; admins approve.

SCOPE
This is a live-demo prototype on free hosting. It must be better than a throwaway script but is not production grade. Do real security basics. Skip scaling work, SSO and billing.

STACK
Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async with asyncpg on Neon Postgres, Alembic, httpx. React 18 with Vite and Tailwind, served by FastAPI after build. GitHub Actions for CI. Render (Docker, free plan) for deployment, deploying only after CI passes. One instance, one uvicorn worker, in-memory state for rate limits and circuit breaker.

NON-NEGOTIABLES
1. Provider keys are Fernet-encrypted at rest. Platform keys are stored only as an HMAC-SHA256 digest and shown in plaintext once at creation. Never log or return secrets, Authorization headers or prompt text.
2. Every tenant query is scoped by org_id.
3. Explainability: every feature that makes a decision or computes a number stores structured facts at that moment. The Explain layer reads stored facts only. It never recomputes values and never invents numbers.
4. Money is integer micro-USD. No floats for money.
5. Do only the current stage. Do not add features or dependencies outside the plan without saying why.

HOW YOU WORK
- Read AGENTS.md and docs/PLAN.md before anything else. Work one stage at a time, in order.
- At the start of a stage, restate its steps and gate as a checklist and list the files you will touch.
- Write tests together with the code. Mock providers with respx. Never use real keys or the network in tests.
- At the end of a stage run the full validation from AGENTS.md plus the stage gate. If anything fails, fix the root cause. Never skip, loosen or delete a test to pass.
- Commit as stage-N with a short summary, push, and confirm CI is green.
- Report: files changed, commands run with results, each gate check as pass or fail, open issues. Then stop and wait for approval before the next stage.
- If a requirement is ambiguous, choose the simplest option consistent with AGENTS.md, state the assumption in your report, and ask only if you are blocked.
- Existing code is trusted only as far as its tests. Read before changing. Use git mv for moves.
```

## AGENTS.md

Save this as AGENTS.md at the repo root.

```markdown
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
- Neon URLs: convert `postgresql://` to `postgresql+asyncpg://` and replace `sslmode=require` with `ssl=require`, which asyncpg expects.
- Run one uvicorn worker. In-memory state resets on restart and must never corrupt data.
- Render's free filesystem is ephemeral: write no files at runtime.
- Streaming: fall back only before the first byte; always close upstream responses.
- The final streaming chunk can have an empty `choices` list.
- Gemini keys arrive in the x-goog-api-key header.

## Definition of done for a stage
All steps implemented, tests written, full validation green, gate checks passed, committed, CI green, report delivered.
```

## Dependencies

requirements.txt. After the first successful install, the agent pins the exact versions it installed.

```text
fastapi>=0.115
uvicorn[standard]>=0.30
pydantic>=2.8
pydantic-settings>=2.4
email-validator>=2.1
sqlalchemy[asyncio]>=2.0
asyncpg>=0.29
alembic>=1.13
httpx>=0.27
cryptography>=43
argon2-cffi>=23.1
pyjwt>=2.9
pyyaml>=6.0
prometheus-client>=0.20
python-json-logger>=2.0
```

requirements-dev.txt:

```text
pytest>=8
pytest-asyncio>=0.24
pytest-cov>=5
respx>=0.21
ruff>=0.6
locust>=2.31
```

frontend/package.json: dependencies react, react-dom, react-router-dom, @tanstack/react-query, recharts, lucide-react. Dev dependencies vite, @vitejs/plugin-react, typescript, tailwindcss, postcss, autoprefixer, eslint, vitest, @testing-library/react, @playwright/test. Scripts: dev, build, lint, typecheck, test.

Presidio is dropped; PII redaction uses the existing regex fallback.

## CI/CD and hosting files

GitHub Actions checks every push and pull request. Render deploys main only after those checks pass. Confirm the autoDeployTrigger field against Render's current blueprint docs.

.github/workflows/ci.yml:

```text
name: CI
on:
  push:
    branches: [main, omnikey-v2]
  pull_request:
jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: omnikey_test
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready --health-interval 5s --health-retries 10
    env:
      ENV: test
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/omnikey_test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: ruff check . && ruff format --check .
      - run: alembic upgrade head
      - run: pytest -q
  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - run: npm ci
      - run: npm run lint
      - run: npm run typecheck
      - run: npm test -- --run
      - run: npm run build
```

Dockerfile:

```text
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=web /web/dist ./frontend/dist
CMD alembic upgrade head && uvicorn codeflux.app:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1
```

render.yaml:

```text
services:
  - type: web
    name: omnikey
    runtime: docker
    plan: free
    branch: main
    healthCheckPath: /healthz
    autoDeployTrigger: checksPass
    envVars:
      - key: ENV
        value: prod
      - key: DEMO_MODE
        value: 'true'
      - key: DATABASE_URL
        sync: false
      - key: MASTER_KEY
        sync: false
      - key: CORS_ORIGINS
        sync: false
      - key: JWT_SECRET
        generateValue: true
      - key: KEY_HMAC_SECRET
        generateValue: true
```

## Step-by-step implementation plan

Run the stages in order. A stage starts only when the previous gate has passed.

**Validation protocol, applied after every stage:**

1. Run the full validation listed in AGENTS.md (ruff, alembic, pytest, frontend checks once the frontend exists).
2. Run the stage's gate checks and keep their output.
3. Fix every failure at its root cause. Never skip, loosen or delete a failing test.
4. Commit as stage-N, push, and confirm CI is green.
5. Report files changed, commands run, gate results and open issues, then wait for approval.

### Stage 0: Branch, cleanup, structure and CI

1. Tag the current commit v1-streamlit and create branch omnikey-v2.
2. Add AGENTS.md, docs/PLAN.md, requirements.txt, requirements-dev.txt, .env.example and .gitignore from this document.
3. Delete planner.py, runner.py, checks.py, streamlit\_app.py, demo/, codeflux-ide-smoke/, scripts/seed\_ide\_smoke.py, understand\_codeflux.md, the /v1/ide/\* routes, the Workflow and ChecklistItem models, their tests, and the Streamlit, Pandas and Redis dependencies and compose services.
4. Move the remaining modules into the structure above with git mv, fix imports, change no behavior.
5. Configure ruff and pytest in pyproject.toml; add GET /healthz; add .github/workflows/ci.yml without the alembic step (Stage 1 adds it).
6. After the first clean install, pin exact installed versions in requirements.txt.

**Gate:** the surviving tests pass after the move; CI is green on a pull request; a search for the removed module names finds nothing.

### Stage 1: Postgres and data model

1. Switch storage to SQLAlchemy 2 async with asyncpg, using the Neon URL conversion from AGENTS.md; remove SQLite-specific code (manual ALTER TABLE, WAL pragmas).
2. Add Alembic and define models in codeflux/db/models.py. Every tenant table carries org\_id: orgs, users, provider\_credentials, platform\_keys (credit\_limit\_micro, credit\_remaining\_micro, rpm\_limit, allowed\_routes, expires\_at, revoked\_at), routes, limit\_requests, credit\_ledger, request\_traces (facts JSON), sessions, session\_messages, arena\_runs (facts JSON).
3. Add indexes on request\_traces (org\_id, created\_at) and credit\_ledger (key\_id, created\_at).
4. Generate the initial migration; add the Postgres service and the alembic step to CI.
5. Make tests use Postgres with per-test rollback fixtures.

**Gate:** alembic upgrade head, downgrade base and upgrade head all succeed on an empty database; the test suite runs on Postgres in CI.

### Stage 2: Security primitives and auth

1. security/crypto.py: Fernet encrypt and decrypt for provider keys; generate\_platform\_key (ok\_live\_ plus 32 random url-safe bytes); hash\_platform\_key (HMAC-SHA256 with KEY\_HMAC\_SECRET); constant-time verify.
2. security/passwords.py (argon2) and security/tokens.py (JWT HS256, 12 hours, httpOnly cookie); api/deps.py with require\_user and require\_admin.
3. settings.py with pydantic-settings: outside ENV=test, refuse to start if a secret is missing or a known default; in ENV=test generate throwaway secrets.
4. security/redaction.py: a logging filter masking ok\_live\_, sk- and AIza patterns and Authorization headers, installed on the root logger.

**Gate:** tests cover encrypt-decrypt round trip, tampered ciphertext rejected, hash deterministic and different from plaintext, generated keys unique, wrong password rejected, expired JWT rejected, app refusing to boot with a default secret, and log redaction.

### Stage 3: Management API

All routes live under /api, validate input with Pydantic, are org-scoped and use cursor pagination.

1. Auth: signup (an admin creates an org; a member joins with an invite code), login, logout, me.
2. Vault (admin): add a provider key (make one cheap test call, encrypt, store the last 4 characters), list, disable, delete.
3. Platform keys (admin): create with owner, credit limit, RPM limit, allowed routes and expiry, returning the plaintext once; list; patch limits; revoke.
4. Routes (admin): CRUD for alias, strategy, task tag and the ordered candidate list.
5. Limit requests: a member creates and lists their own; an admin lists pending, approves with an editable new limit (writes a ledger credit entry) or denies.

**Gate:** API tests show a member gets 403 on admin routes, a cross-org read returns 404, the platform key plaintext appears only in the create response, no response contains an encrypted key or a digest, and approving a request changes the limit and writes a ledger row.

### Stage 4: Gateway core, single provider path

1. Authenticate /v1 requests by Authorization Bearer, x-api-key or x-goog-api-key (query-string key only on /v1beta). Reject unknown, revoked or expired keys with 401 and zero-credit keys with 429 code insufficient\_credits, in the OpenAI error envelope.
2. Add an in-memory sliding-window RPM limiter per key returning 429 with Retry-After.
3. Adapters: fix the empty-choices crash on the final stream chunk, implement real Gemini SSE streaming, always close upstream responses, and use one shared httpx.AsyncClient created in the app lifespan with connection limits and per-request deadlines.
4. Endpoints: POST /v1/chat/completions, GET /v1/models, and a non-streaming POST /v1beta/models/{model}:generateContent.
5. Read token usage from the response; when absent, estimate characters divided by 4 and flag it as estimated.
6. Read CORS origins from CORS\_ORIGINS.

**Gate:** respx tests cover non-stream, stream, the empty-choices final chunk, unknown key 401, revoked key 401, RPM 429 and Gemini-shaped output. As a manual smoke test, the official OpenAI SDK pointed at the local server gets a real reply from one free-tier key; paste the output.

### Stage 5: Metering and credits

1. metering/pricing.py: input and output micro-USD per 1M tokens per model, a price\_version, and a list price for free-tier models so savings can be shown. Label every figure an estimate.
2. compute\_cost(tokens, model) returns charged and list cost, price\_version and the price rows used.
3. In a background task after the response: atomically decrement the key's remaining credits with one SQL UPDATE, insert a ledger row with balance\_after, and write the trace with token and cost facts.
4. Add /api/admin/usage and /api/member/usage: totals by key and model, cost per 1K tokens, credits remaining, and the ledger list.

**Gate:** cost tests match hand-calculated cases; two concurrent requests both deduct with no lost update; ledger entries sum to the limit minus the remaining credits; a key at zero credits is refused with a clear error.

### Stage 6: Routing, fallback and key pooling

1. Resolve the model field: a route alias uses that route's candidates; a concrete model becomes one candidate followed by the org's default fallback route.
2. Implement the strategies priority, round-robin and least-latency (latency average kept in memory).
3. Support per-request overrides, checked against the key's allowed routes: header X-OmniKey-Task selects the route with that task tag; header X-OmniKey-Fallback takes a comma list such as groq/llama-3.3-70b,gemini/gemini-2.0-flash.
4. Pool keys per provider: pick the least recently used enabled key; on 429 set a cooldown from Retry-After; on 401 disable that key and note it in the trace.
5. Circuit breaker in memory: open after repeated failures for 30 seconds, then allow one half-open probe. The probe carries an expiry (30 seconds, monotonic clock) so an abandoned probe releases itself, and dispatch uses try/finally so every attempt reports success or failure.
6. Fall through on 429, 5xx, timeout, network error and open circuit; never on a client 400. For streams, fall back only before the first byte; afterwards send a clean SSE error event.
7. Record every attempt on the trace: provider, model, key hint, outcome (skipped, failed, succeeded), HTTP status, latency and a reason code from a fixed list.
8. With DEMO\_MODE on, add an admin endpoint that toggles an in-memory outage flag per provider, making it answer 429.

**Gate:** tests cover fallback on 429, timeout and 5xx; no fallback on 400; the breaker opens then recovers; an abandoned probe releases after its expiry; the task header picks the tagged route; the custom fallback header is honored; a disallowed model is rejected; stream fallback happens only before the first byte; the attempts array matches each scenario exactly.

### Stage 7: Context sessions

1. Accept header X-OmniKey-Session; create the session on first use, scoped to the org and the key.
2. Load stored messages, append the incoming ones, trim the oldest turns to the candidate's budget (characters divided by 4; default 6000 tokens, overridable per model in the pricing table), then dispatch.
3. Store the assistant reply in a background task after success.
4. Put into the trace facts: context carried, messages sent, messages trimmed and whether the provider changed.
5. Expire sessions on read after 24 hours; add member endpoints to list and delete sessions.

**Gate:** a test sends request 1 to provider A, forces A down, sends only a short follow-up, and confirms provider B received the full earlier history; trimming keeps the newest turns; a different key cannot read the session.

### Stage 8: Explain engine

1. In explain/facts.py define a Pydantic model of facts for each kind: trace, cost, credits, usage, blocked, compare, debate. Features write these as they run; refused requests also write a trace with outcome blocked and the failed check.
2. In explain/templates.py write one function per kind returning headline, bullets and facts. Templates must cover: a fallback happened and why, skipped candidates and why, charged cost versus list price, how the credit balance follows from ledger entries, and why a request was blocked.
3. Add GET /api/explain/{kind}/{id}, org-scoped, members limited to their own records.
4. Add POST /api/explain/{kind}/{id}/narrate: send only the facts JSON to a model through the gateway, with a prompt that forbids new numbers. Extract every number from the reply; if any is missing from the facts, discard the reply and return the deterministic text. Cache accepted narrations in the facts.
5. Add response headers on gateway calls: X-OmniKey-Trace-Id, X-OmniKey-Provider, X-OmniKey-Model, X-OmniKey-Attempts, X-OmniKey-Latency-Ms, X-OmniKey-Credits-Remaining.

**Gate:** snapshot tests per kind with fixed facts; the narration guard rejects a reply containing an invented number; another org's record returns 404; header values match the stored trace.

### Stage 9: Playground and arenas

1. Playground: POST /api/playground/chat with format (openai or gemini), model, messages, optional session id and stream flag. It uses the real gateway code path and bills the caller's chosen key. It returns the reply, the raw request and response in the chosen format, latency, tokens and the trace id.
2. Compare Arena: POST /api/arena/compare with a prompt, up to 4 models and an optional judge flag. Run models in parallel with no fallback. Return per model: output, latency, tokens, character count, cost and error; keep partial results when one model fails. The judge scores accuracy, clarity and completeness from 1 to 10 with a one-line reason each, as JSON validated by Pydantic (retry once, then show unscored). Compute the ranking in code from the scores, with cost and latency as tie-breaks. Label judge output AI-judged.
3. Debate Arena: POST /api/arena/debate with topic, model A, model B, judge model and rounds (default 2, max 3). Assign the sides FOR and AGAINST, cap each turn at 120 words, and run turns in sequence with the transcript. The judge scores each side on argument strength, evidence and rebuttal from 1 to 10; compute the verdict in code. Cap total tokens per run.
4. Both arenas bill the caller's key, write traces, and store their facts, including rubric and raw scores, in arena\_runs.

**Gate:** compare returns partial results when one model errors; ranking is deterministic for fixed scores; an invalid judge reply degrades gracefully; the debate stops at its round and token caps; explain endpoints return correct output for playground, compare and debate records.

### Stage 10: Frontend

| Route | Who | Content |
| --- | --- | --- |
| / | Public | Hero (One key. Every model.), three steps (plug in your keys, create an OmniKey, change your base URL), before and after code snippet, feature grid, Login / Sign up button at the top right |
| /auth | Public | Login and Sign up tabs; Sign up has an Admin or Member switch (admin creates a workspace, member joins with an invite code) |
| /admin | Admin | Stat cards (requests, tokens, spend, fallback rate, p95 latency), usage chart, per-provider split |
| /admin/vault | Admin | Provider keys with hint, status and last used; add, disable, delete |
| /admin/keys | Admin | Key table (owner, prefix, credits bar, RPM, expiry, status); create dialog with one-time reveal, copy button and code snippets |
| /admin/routes | Admin | Drag-to-reorder fallback chains, strategy, task tag |
| /admin/requests | Admin | Pending limit requests with approve (editable limit) or deny |
| /admin/traces | Admin | Trace list; detail view with attempt timeline and Why panel |
| /app | Member | Own keys, credits remaining, cost per 1K tokens, snippets, request-more form, own activity |
| /playground, /arena/compare, /arena/debate | Both | The Stage 9 features |

1. Scaffold frontend/ with Vite and Tailwind, a typed API client that sends the cookie, and role-based route guards.
2. Build the shared components first: WhyPanel, UsageBar, KeyRevealDialog, AttemptTimeline.
3. Build the pages in the table's order.
4. Put a Why? control beside every cost, credit, routing and arena result that opens WhyPanel for that record.
5. Add loading, empty and error states, a mobile-responsive layout, and a banner reading: Demo environment, do not enter production keys.
6. Serve frontend/dist from FastAPI with a fallback to index.html for non-API paths; proxy /api and /v1 to port 8000 in Vite dev.

**Gate:** a Playwright smoke test completes the admin flow (sign up, add key, create route, create key, see trace) and the member flow (sign up, see key, request increase) with no console errors; screenshots at 390px and 1280px show no horizontal overflow; the frontend CI job passes.

### Stage 11: Seed data and demo script

1. Write scripts/seed.py: a demo org, one admin, two members, routes fast, smart and code from config/routes.yaml, and about 200 synthetic traces over 7 days marked as demo data, with ledger entries consistent with the keys.
2. Write DEMO.md: the five-minute walkthrough (problem, plug in keys, create key, curl, simulate outage, read the Why panel, continue a session, compare, debate, limit request and approval).

**Gate:** the seed runs twice without duplicating data; dashboard charts are populated; the Stage 5 ledger invariant still holds after seeding.

### Stage 12: Deploy and end-to-end check

1. Create a free Neon project and copy its connection string, converted to the asyncpg form, into DATABASE\_URL.
2. Generate MASTER\_KEY with python -c 'from cryptography.fernet import Fernet; print(Fernet.generate\_key().decode())'.
3. In Render choose New, then Blueprint, select the repo, and fill the sync:false values from render.yaml.
4. In GitHub, protect main by requiring the CI checks; merge omnikey-v2 through a pull request so Render deploys after checks pass.
5. Run the seed against the Neon database, then optionally add a free pinger on /healthz every 10 minutes.
6. Run every scenario below against the live URL.

| # | Scenario | Expected result |
| --- | --- | --- |
| 1 | Admin signs up and adds a free-tier provider key | Key listed with its hint only |
| 2 | Create route smart with two providers; create a platform key with 1 USD credit and 10 RPM | Plaintext shown once |
| 3 | curl with the key | 200 and X-OmniKey headers present |
| 4 | Simulate an outage on the primary provider and repeat the call | 200 from the second provider; trace shows failed 429 then succeeded; Why panel says so |
| 5 | Two calls in one session across the outage | Second answer uses the earlier context |
| 6 | 11 calls within a minute | 429 with Retry-After |
| 7 | Spend the credits to zero | Refused with insufficient\_credits; Why panel explains |
| 8 | Member requests an increase; admin approves | Limit and ledger update; calls succeed again |
| 9 | Compare three models | Results, ranking and Why panel |
| 10 | Run a debate | Verdict and Why panel |
| 11 | Revoke the key | Next call returns 401 |
| 12 | Inspect the database and logs | No plaintext provider or platform keys anywhere |

**Gate:** all 12 scenarios pass on the live URL. Fix any failure and rerun the whole list.

## Known limits to state in your report

- Free-tier provider limits and model names change; check each provider's docs when configuring routes.
- Cost figures come from a static price table and are estimates.
- Credits are deducted after the response, so concurrent in-flight calls can overrun a balance slightly.
- Judge scores are model opinions, labeled AI-judged; rankings are computed in code from them.
- Render's free service sleeps after idle time and wakes in about a minute; in-memory state (circuit breaker, rate limits, outage flags) resets then. Data lives in Neon and survives.
- One instance and one worker is a demo design, not a scaling design.

Sources: [Render free tier docs](https://render.com/docs/free).
