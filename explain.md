# CodeFlux — Comprehensive Architecture & Technical Specification

> **CodeFlux** is a self-hosted, multi-provider AI gateway, quota-pooling manager, and persistent work planner. It exposes unified OpenAI- and Gemini-compatible API endpoints while orchestrating upstream provider selection, least-recently-used (LRU) credential rotation, automatic failover, circuit breaking, and offline local model fallbacks.

---

## 1. The Core Problem CodeFlux Solves

When developing applications powered by Large Language Models (LLMs), engineering teams face four major bottlenecks:

1. **Quota Exhaustion & Rate Limits (429 Errors)**: Individual API keys frequently hit rate limits (Requests Per Minute / Tokens Per Minute) or account quota limits.
2. **Provider Lock-in & Incompatible Formats**: OpenAI and Google Gemini use fundamentally different request/response JSON schemas (`messages` vs `contents/systemInstruction`).
3. **Transient Provider Outages**: Cloud LLM APIs experience latency spikes, regional downtime, and temporary service degradation (503 / 500 errors).
4. **Fragile Agentic Workflows**: Long-running AI tasks lose context when providers fail mid-execution because progress is tied to a single chat session.

**CodeFlux solves all four:**
- It allows pooling multiple API keys across teammates or accounts and rotates them automatically.
- It normalizes incoming requests bi-directionally between OpenAI and Gemini formats.
- It provides cascading failover (e.g., OpenAI → Gemini → Groq → Local Ollama).
- It introduces a database-persisted checklist workflow so tasks can be paused, resumed, or handed over across different AI models without loss of state.

---

## 2. System Architecture & Component Diagram

```
+-----------------------------------------------------------------------------------+
|                                  CLIENT LAYER                                     |
|  +--------------------+  +----------------------+  +---------------------------+  |
|  | Streamlit UI       |  | Third-Party LLM Apps |  | Developer SDKs / Scripts  |  |
|  | (:8501 Control Rm) |  | (Cursor, LangChain)  |  | (curl, openai-python)     |  |
|  +--------------------+  +----------------------+  +---------------------------+  |
+------------------------------------------+----------------------------------------+
                                           |
                   Authorization: Bearer <GATEWAY_KEY>
                                           v
+-----------------------------------------------------------------------------------+
|                         CODEFLUX GATEWAY CORE (:8000)                             |
|                                                                                   |
|  1. Authentication Middleware (codeflux/auth.py)                                 |
|     Verifies Bearer token against CODEFLUX_GATEWAY_KEYS                           |
|                                                                                   |
|  2. Schema Normalization (codeflux/normalization.py)                             |
|     Converts OpenAI/Gemini JSON -> Unified NormalizedRequest                      |
|                                                                                   |
|  3. PII Redaction Layer (codeflux/pii.py)                                        |
|     Masks emails, credit cards, phones, and secrets (if route.pii_redaction=true) |
|                                                                                   |
|  4. Routing Engine (codeflux/router.py)                                           |
|     Matches route alias (gpt-4-tier, gemini-tier)                                 |
|     Orders candidates: priority | round-robin | least-latency | weighted-random   |
|                                                                                   |
|  5. Quota Pool & Key Manager (codeflux/keys.py)                                   |
|     Retrieves provider keys from CredentialVault                                  |
|     Applies LRU rotation + checks reset times from x-ratelimit-* headers          |
|                                                                                   |
|  6. Circuit Breaker (codeflux/circuit.py)                                         |
|     Tracks failure thresholds (Closed -> Open -> Half-Open cooldown)              |
+--------------------+---------------------+--------------------+-------------------+
                     |                     |                    |
                     v                     v                    v
         +-----------------------+ +---------------+ +--------------------+
         |   Google Gemini API   | |  OpenAI API   | |  Groq / Other Wire |
         | gemini-3.1-flash-lite | |  gpt-4o-mini  | |  llama-3.3-70b     |
         +-----------------------+ +---------------+ +--------------------+
                                           | (Failover if cloud down/unreachable)
                                           v
                               +-----------------------+
                               | Local Ollama Server   |
                               | llama3.2 (:11434)     |
                               +-----------------------+

+-----------------------------------------------------------------------------------+
|                          PERSISTENCE LAYER (SQLite)                               |
|                                                                                   |
|  - credentials:     AES-encrypted provider keys (Fernet + SHA-256 master key)     |
|  - usage_records:   Per-team, per-model prompt & completion token telemetry       |
|  - workflows:       Master prompt projects & task titles                          |
|  - checklist_items: Persisted steps, checkboxes & completion state                |
+-----------------------------------------------------------------------------------+
```

---

## 3. Detailed Request Flows

### Flow A: An AI Completion / Checklist Request

1. **Incoming Request**:
   The client sends an HTTP POST request to `/v1/chat/completions` (OpenAI format) or `/v1beta/models/{route}:generateContent` (Gemini format) with `Authorization: Bearer <GATEWAY_KEY>`.
2. **Authentication**:
   `codeflux/auth.py` matches the provided token against configured `CODEFLUX_GATEWAY_KEYS`. If invalid, HTTP 401 is immediately returned. The request is assigned a `team` context.
3. **Normalization**:
   `codeflux/normalization.py` parses the JSON body into a unified `NormalizedRequest` object containing standardized message roles (`system`, `user`, `assistant`), generation parameters, and tools.
4. **PII Sanitization**:
   If the matching route has `pii_redaction: true`, `codeflux/pii.py` runs regex patterns over prompt text to redact emails, phone numbers, credit cards, and common API secret tokens.
5. **Route Candidate Selection**:
   The `RoutingEngine` looks up the route definition in `config/routes.yaml`:
   - It orders the candidate providers according to the route strategy (`priority`, `least-latency`, etc.).
   - It computes the overall request deadline (`monotonic time + route.total_timeout_seconds`).
6. **Key Selection via Quota Pool**:
   For the candidate provider, `KeyPool.select(provider)`:
   - Queries the encrypted `CredentialVault` for all active keys assigned to that provider.
   - Evaluates the rate-limit state (`remaining_requests` and `reset_at` timestamps).
   - Selects the least recently used (LRU) eligible key.
   - Decrypts the secret in-memory using Fernet symmetric encryption.
7. **Circuit Breaker Check**:
   Before executing the request, the circuit breaker verifies that `provider:key_ref` is not in an `OPEN` state (tripped by consecutive previous errors).
8. **Provider Invocation**:
   The provider adapter (`GeminiAdapter` or `OpenAICompatibleAdapter`) issues the async HTTP request via `httpx.AsyncClient`.
9. **Outcome Handling**:
   - **On Success**: CodeFlux parses any `x-ratelimit-*` headers to update quota records, resets the circuit failure count to 0, records prompt and completion token counts in SQLite, and returns the converted response to the client.
   - **On Failure (429, 500, timeout, quota empty)**: CodeFlux logs a warning, records a failure in the circuit breaker, and immediately loops to the next candidate model in the route until the request succeeds or the deadline expires.
10. **Terminal Fallback**:
    If all external cloud providers fail, CodeFlux routes the prompt to the local **Ollama** daemon (`llama3.2`) if configured in the route.

---

### Flow B: Quota Pool Credential Onboarding

1. The administrator or authorized contributor opens the **Quota pool** tab in the Streamlit control room (`http://localhost:8501`).
2. They specify a contributor name, select the provider (e.g. `gemini`, `openai`, `groq`), and enter the raw API key.
3. Streamlit invokes `with_storage("put_credential", ...)`:
   - Derives a 256-bit encryption key from `CODEFLUX_MASTER_SECRET` via SHA-256 and base64 URL-encoding.
   - Encrypts the raw key with Fernet symmetric encryption.
   - Generates a unique reference tag (e.g., `gemini-alice-4f1a9c`).
   - Persists the record to the `credentials` table in SQLite.
4. The plaintext key is discarded from memory. The UI displays only the reference and masked metadata.

---

### Flow C: Persistent Work Planner

1. In the **Work planner** tab, the user inputs a **Project Title** and a **Master Prompt**.
2. Streamlit sends the master prompt to `/v1/chat/completions` with a system prompt instructing the model to produce a strict JSON array of ordered checklist steps.
3. CodeFlux executes the prompt through the active failover route.
4. The response is parsed into individual checklist items and stored in SQLite under `workflows` and `checklist_items` tables.
5. Users can toggle checkboxes, add manual steps, and track progress percentages.
6. When the user clicks **Do the work**:
   - Streamlit constructs an execution prompt containing the master goal, completed items, and pending items.
   - The request is dispatched through CodeFlux.
   - The AI output is saved permanently in SQLite under the workflow record so any subsequent provider or session can continue from the exact saved checkpoint.

---

## 4. Tech Stack & Engineering Choices

| Layer | Technology | Rationale |
| :--- | :--- | :--- |
| **API Framework** | **FastAPI** | High-performance asynchronous ASGI framework; native Pydantic validation; automatic OpenAPI/Swagger documentation at `/docs`. |
| **ASGI Web Server** | **Uvicorn** | Fast, production-ready ASGI server built on `uvloop` and `httptools`. |
| **Admin Control Room** | **Streamlit** | Rapid, stateful interactive dashboard for real-time telemetry, credential pooling, and master-prompt checklist management without custom frontend build steps. |
| **HTTP Client** | **HTTPX (AsyncClient)** | Asynchronous HTTP client supporting HTTP/1.1 and HTTP/2, request pooling, streaming responses, and configurable timeouts. |
| **Data Persistence** | **SQLite + SQLAlchemy 2.0 (aiosqlite)** | Zero-configuration, serverless single-file database supporting full ACID guarantees; fully async queries prevent event-loop blocking. |
| **Data Encryption** | **Cryptography (Fernet / AES-128-CBC + HMAC-SHA256)** | Industry-standard authenticated symmetric encryption. Raw keys are never stored in plaintext. |
| **Configuration & Validation** | **Pydantic Settings & PyYAML** | Strictly typed configuration schema loading `.env` variables and YAML route definitions with validation at startup. |
| **Telemetry & Metrics** | **Prometheus Client** | Exposes standardized metrics (`requests_total`, `tokens_total`, `latency_seconds`, `circuit_breaker_state`) on `/metrics`. |
| **Containerization** | **Docker & Docker Compose** | Reproducible multi-container stack provisioning CodeFlux gateway, Streamlit dashboard, Redis, and local Ollama. |

---

## 5. Codebase Component Directory

```text
CodeFlux/
├── codeflux/
│   ├── adapters/
│   │   ├── base.py                 # Abstract base class defining provider interface
│   │   ├── gemini.py               # Native Gemini generateContent adapter
│   │   ├── openai_compatible.py    # Universal OpenAI wire protocol adapter (OpenAI, Groq, OpenRouter, Mistral)
│   │   └── registry.py             # Instantiates and holds available provider adapters
│   ├── app.py                      # FastAPI factory, endpoints, and application lifespan
│   ├── auth.py                     # Gateway Bearer token authentication dependency
│   ├── circuit.py                  # In-memory circuit breaker state machine
│   ├── config.py                   # Pydantic models for routes, settings, and candidates
│   ├── errors.py                   # Custom exceptions (ProviderError, NoProviderAvailable)
│   ├── keys.py                     # Quota-aware LRU key pool selector
│   ├── logging.py                  # Structured JSON logging configuration
│   ├── metrics.py                  # Prometheus metric definitions
│   ├── normalization.py            # Bi-directional payload conversion between OpenAI and Gemini
│   ├── pii.py                      # Regex-based PII scrubber
│   ├── router.py                   # Multi-candidate failover routing engine
│   ├── schemas.py                  # Normalized internal representations of requests and responses
│   └── storage.py                  # SQLAlchemy async models, CredentialVault, and Workflows
├── config/
│   └── routes.yaml                 # Active route aliases, candidate models, and timeouts
├── tests/                          # Pytest test suite covering failover, circuits, keys, and UI
├── docker-compose.yml              # Multi-container deployment specification
├── Dockerfile                      # Container image definition
├── pyproject.toml                  # Project packaging and dependency definitions
├── streamlit_app.py                # Streamlit control room and UI
├── explain.md                      # Complete system explanation (this document)
└── README.md                       # Quickstart, installation, and deployment guide
```

---

## 6. Security & Privacy Guarantees

1. **Encrypted Credentials**: Plaintext provider keys exist in memory only during the lifecycle of an outbound HTTP call. They are stored in SQLite using Fernet encryption derived from `CODEFLUX_MASTER_SECRET`.
2. **Credential Isolation**: Client applications communicate exclusively using CodeFlux Gateway Keys (`CODEFLUX_GATEWAY_KEYS`). Upstream provider API keys are never leaked to client callers.
3. **PII Masking**: Prompts routed through routes with `pii_redaction: true` strip sensitive personal information before external transmission.
4. **Dashboard Access Control**: The Streamlit control room is guarded by `CODEFLUX_DASHBOARD_PASSWORD` using constant-time hash comparison (`hmac.compare_digest`) to prevent timing attacks.
