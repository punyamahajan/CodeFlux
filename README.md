# OmniKey: Unified, Explainable AI Gateway

OmniKey (package `codeflux`) is an enterprise-grade AI gateway that lets organizations pool upstream LLM provider credentials, issue governed and metered platform keys (`ok_live_...`), dynamically route inference requests with automatic fallback, and provide 100% explainable auditing for every routing decision, token, and micro-USD spent.

---

## 🌟 Key Features

1. **Unified Provider Key Pooling & Vault**:
   - Centralize provider keys (OpenAI, Gemini, Groq, Mistral, Together, OpenRouter, Ollama) in an encrypted vault.
   - Keys are encrypted with **Fernet (AES-128-CBC + HMAC-SHA256)** using a derived master secret.
   - Provider credentials are live-probed before being enabled and display only masked hints (`...1234`).

2. **Scoped Platform Keys & Credit Budgets**:
   - Issue platform keys (`ok_live_...`) to teams, engineers, or services.
   - Plaintext keys are returned strictly once at generation time. Only salted **HMAC-SHA256** digests are stored in the database.
   - Enforce hard credit limits in micro-USD ($1.00 = 1,000,000 micro-USD) with double-entry ledger deduction.
   - Sliding-window RPM limits, route whitelists, and expiration timestamps.

3. **Intelligent Dynamic Routing & Fallback**:
   - Support multiple routing strategies: `priority`, `least-latency`, `round-robin`, `weighted-random`.
   - Automatic provider failover: if primary candidate is rate-limited (429) or times out (504), requests fall back immediately to secondary providers.
   - Circuit breakers track failures per candidate (`failure_threshold`, `cooldown_seconds`).
   - Seamless streaming support (SSE chunks streamed directly to client; failover occurs before first byte).

4. **Multi-Turn Session Continuity**:
   - Sessions maintain conversation context even when fallback switches providers across turns (e.g. Turn 1 on Gemini, Turn 2 on Groq).
   - Smart sliding-window context compression with token budget trimming and summary preservation.

5. **Explainable AI (XAI) Engine & Guarded Narration**:
   - Every request logs a structured facts JSON with schema versioning (`TraceFacts`, `CostFacts`, `CreditsFacts`, `BlockedFacts`, `CompareFacts`, `DebateFacts`).
   - Deterministic Plain-English templates explain **why** a specific candidate was chosen, which keys were attempted, latency breakdown, and exact cost math.
   - **AI Narration Guard**: An LLM narrator provides rich human-friendly summaries of the facts. A strict validation guard rejects any narration that invents or hallucinated numbers not present in the stored facts.

6. **Interactive Arenas & Playground**:
   - **Interactive Playground**: Send test messages in standard OpenAI or Gemini JSON schemas directly through the gateway.
   - **Compare Arena**: Head-to-head battle comparing up to 4 models concurrently with impartial AI judge scoring across Accuracy, Clarity, and Completeness.
   - **Debate Arena**: Multi-turn Oxford-style debate on any user prompt, enforcing strict word caps, turn limits, and judge scoring.

---

## 🏗️ Architecture

```
                                      ┌────────────────────────────────────────────────────────┐
                                      │                     Client Application                 │
                                      └───────────────────────────┬────────────────────────────┘
                                                                  │ Bearer ok_live_...
                                                                  ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       OmniKey Gateway Core                                   │
│                                                                                              │
│   ┌──────────────────────┐    ┌──────────────────────┐    ┌──────────────────────────────┐   │
│   │ Platform Key Auth &  │───▶│   Sliding Window     │───▶│ Double-Entry Credit Ledger   │   │
│   │ HMAC Verification    │    │   RPM Rate Limiter   │    │ Invariant: Bal = Limit + Sum │   │
│   └──────────────────────┘    └──────────────────────┘    └──────────────┬───────────────┘   │
│                                                                          │                   │
│                                                                          ▼                   │
│   ┌──────────────────────────────────────────────────────────────────────────────────────┐   │
│   │                                 Routing Engine & Circuits                            │   │
│   │                                                                                      │   │
│   │   [Fast: Groq ➡️ Gemini ➡️ OpenAI]   [Smart: Gemini ➡️ Groq ➡️ OpenAI]   [Code]        │   │
│   └──────────────────────────────────────────┬───────────────────────────────────────────┘   │
│                                              │                                               │
│                                              ▼                                               │
│   ┌──────────────────────┐    ┌──────────────────────┐    ┌──────────────────────────────┐   │
│   │  Groq (OpenAI Comp)  │    │  Gemini REST Adapter │    │   OpenAI / Local Ollama      │   │
│   └──────────────────────┘    └──────────────────────┘    └──────────────────────────────┘   │
│                                                                                              │
│   ┌──────────────────────────────────────────────────────────────────────────────────────┐   │
│   │                             Structured Facts & Explain Engine                        │   │
│   │   • Deterministic Fact Renderers   • Numbers Validation Guard   • AI Narration       │   │
│   └──────────────────────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quickstart & Setup

### 1. Requirements
- Python 3.12+
- Node.js 18+ (for frontend)
- PostgreSQL database (e.g. Neon Postgres direct connection string)

### 2. Environment Configuration
Create a `.env` file in the project root:
```env
CODEFLUX_ENV=dev
CODEFLUX_MASTER_KEY=your-32-byte-fernet-master-key-base64
CODEFLUX_JWT_SECRET=your-jwt-auth-secret-string
CODEFLUX_KEY_HMAC_SECRET=your-platform-key-hmac-secret-string
CODEFLUX_DATABASE_URL=postgresql+asyncpg://user:password@host/dbname?ssl=require

# Provider API Keys
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=AQ...
OPENAI_API_KEY=sk-proj-...
OLLAMA_BASE_URL=http://localhost:11434/v1
```

### 3. Installation & Database Setup
```bash
# Setup Python virtual environment
python -m venv .venv
source .venv/bin/activate  # Or on Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt

# Run migrations
alembic upgrade head

# Seed demo organization and synthetic data
python -m scripts.seed

# Build frontend SPA
cd frontend
npm ci
npm run build
cd ..
```

### 4. Running the Application
```bash
# Start backend server (serves both API and SPA Frontend)
uvicorn codeflux.app:app --host 127.0.0.1 --port 8000
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser!

---

## 🔑 Demo Credentials

| Role | Email | Password | Platform Key |
| :--- | :--- | :--- | :--- |
| **Admin** | `admin@omnikey.demo` | `demopassword123` | `ok_live_demo_admin_secret_key_12345` |
| **Member** | `alice@omnikey.demo` | `demopassword123` | `ok_live_demo_alice_secret_key_12345` |
| **Member** | `bob@omnikey.demo` | `demopassword123` | `ok_live_demo_bob_secret_key_12345` |

---

## 📡 API Reference

### Gateway Inference Endpoints
- `POST /v1/chat/completions`: OpenAI-compatible chat completions (supports streaming, tools, fallback headers).
- `POST /v1/completions`: Legacy OpenAI text completion.
- `POST /v1/embeddings`: OpenAI embedding route.
- `POST /v1beta/models/{model}:generateContent`: Gemini-compatible REST completions endpoint.
- `GET /v1/models`: List available routes and candidates.

#### Gateway Response Headers
Every gateway response returns complete routing telemetry:
- `X-OmniKey-Trace-Id`: Unique trace ID (`trc_...`) for Explain lookups.
- `X-OmniKey-Provider`: Upstream provider that handled the request (`groq`, `gemini`, etc.).
- `X-OmniKey-Model`: Target model or route alias used.
- `X-OmniKey-Attempts`: Number of provider candidates attempted.
- `X-OmniKey-Latency-Ms`: Total gateway elapsed time in milliseconds.
- `X-OmniKey-Credits-Remaining`: Remaining key credit balance in micro-USD.

### Management & Explain APIs
- `POST /api/auth/login`: Authenticate with email/password to receive JWT token.
- `GET /api/admin/vault`: List configured provider keys with masked hints.
- `POST /api/admin/vault`: Live-probe and store a new provider credential.
- `GET /api/admin/keys`: List platform keys.
- `POST /api/admin/keys`: Issue a new platform key (`ok_live_...`).
- `GET /api/admin/routes`: List configured routes and candidate priorities.
- `GET /api/admin/traces`: Audit log of request traces with structured facts.
- `GET /api/explain/{kind}/{id}`: Plain-English deterministic explanation for any trace, cost, blocked request, or arena run.
- `POST /api/explain/{kind}/{id}/narrate`: AI narration with strict numeric hallucination guard.
- `POST /api/playground/chat`: Run a chat turn through the live gateway.
- `POST /api/arena/compare`: Run parallel models head-to-head with judge scoring.
- `POST /api/arena/debate`: Run an Oxford-style multi-round debate.

---

## 🧪 Verification & Testing

OmniKey includes a strict verification test suite:

```bash
# 1. Run Python unit and integration tests
pytest -q

# 2. Code style and quality checks
ruff check .
ruff format --check .

# 3. Frontend TypeScript and unit checks
cd frontend
npm run lint
npm run typecheck
npm test -- --run
npm run build
cd ..

# 4. Live End-to-End Integration Test Suite
python scripts/e2e_live_test.py
```

---

## 🛡️ Security & Privacy

- **Zero Secret Leakage**: Provider secrets are never returned in trace logs, API responses, or error details.
- **HMAC Storage**: Platform key secrets are never stored in plaintext; only cryptographically signed digests are persisted.
- **PII Redaction**: Configurable per-route redaction masks emails, SSNs, phone numbers, and API tokens before forwarding upstream.
- **Strict Multi-Tenancy**: All database queries enforce tenant isolation via `org_id`. Members can only access their own records.
