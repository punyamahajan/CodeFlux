# How CodeFlux Works

This document explains the complete CodeFlux system: its purpose, components, data model, authentication, routing, provider-key pooling, token accounting, dashboard, work planner, failure behavior, and deployment boundaries.

## 1. What CodeFlux is

CodeFlux is a self-hosted gateway between a team and multiple large-language-model providers. Instead of configuring every application with separate OpenAI, Gemini, Groq, or OpenRouter credentials, applications call CodeFlux with one CodeFlux API key.

CodeFlux then:

1. Identifies the calling team.
2. Checks its managed monthly token budget.
3. Converts the incoming payload into one internal format.
4. Finds the requested logical route.
5. Selects an eligible provider and encrypted provider key.
6. Calls the provider and fails over when necessary.
7. Converts the result back to the client's expected format.
8. Records token usage for the team.

It also includes a Streamlit control room for provider-key contribution, usage monitoring, teammate access, and persistent AI work checklists.

## 2. High-level architecture

```text
                        +--------------------------+
                        | Streamlit control room   |
                        | localhost:8501           |
                        +------------+-------------+
                                     |
                         API calls + shared storage
                                     |
                                     v
+----------------+       +-----------+------------+       +-------------------+
| App / SDK /    | ----> | FastAPI gateway        | ----> | OpenAI-compatible |
| teammate       | key   | localhost:8000         |       | providers         |
+----------------+       |                        |       +-------------------+
                         | auth and budgets       |
                         | normalization          | ----> +-------------------+
                         | routing and failover   |       | Google Gemini     |
                         | circuit breakers       |       +-------------------+
                         | usage recording        |
                         +-----------+------------+ ----> +-------------------+
                                     |                    | Local Ollama      |
                                     v                    +-------------------+
                         +-----------+------------+
                         | SQLite database        |
                         | encrypted credentials  |
                         | client-key digests     |
                         | usage and workflows    |
                         +------------------------+
```

The normal local deployment has two Python processes:

- `python -m codeflux` starts the FastAPI/Uvicorn gateway on port 8000.
- `streamlit run streamlit_app.py` starts the control room on port 8501.

Both processes use the same `.env`, route configuration, master secret, and SQLite database.

## 3. Repository structure

```text
CodeFlux/
|-- codeflux/
|   |-- adapters/
|   |   |-- base.py                 Provider interface
|   |   |-- gemini.py               Native Gemini adapter
|   |   |-- openai_compatible.py    OpenAI-wire-compatible adapter
|   |   `-- registry.py             Provider adapter registry
|   |-- app.py                      FastAPI application and endpoints
|   |-- auth.py                     Client API-key authentication
|   |-- circuit.py                  In-memory circuit breakers
|   |-- config.py                   Environment and YAML models
|   |-- errors.py                   Gateway/provider exceptions
|   |-- keys.py                     Provider-key LRU selection
|   |-- logging.py                  Structured logging setup
|   |-- metrics.py                  Prometheus metrics
|   |-- normalization.py            External/internal schema conversion
|   |-- pii.py                      Optional prompt redaction
|   |-- router.py                   Routing, failover, and usage recording
|   |-- schemas.py                  Internal request/response models
|   |-- storage.py                  Database models and repositories
|   `-- __main__.py                 Uvicorn entry point
|-- config/routes.yaml              Logical routes and provider candidates
|-- data/codeflux.db                Default SQLite database, created at runtime
|-- tests/                          Automated tests
|-- streamlit_app.py                Team control room
|-- docker-compose.yml              Container stack
|-- Dockerfile                      Application image
|-- .env.example                    Environment template
|-- README.md                       Setup and quick usage
`-- explain.md                      This architecture guide
```

## 4. Configuration

### Environment settings

`codeflux/config.py` loads settings from process environment variables and `.env`. Every setting uses the `CODEFLUX_` prefix.

| Setting | Purpose |
|---|---|
| `CODEFLUX_MASTER_SECRET` | Derives encryption and HMAC keys. It must remain stable. |
| `CODEFLUX_GATEWAY_KEYS` | Bootstrap client keys in `key:team` comma-separated format. |
| `CODEFLUX_DASHBOARD_PASSWORD` | Shared outer password gate for the Streamlit UI. |
| `CODEFLUX_DASHBOARD_GATEWAY_URL` | Gateway URL used by the dashboard. |
| `CODEFLUX_CONFIG_PATH` | Location of `routes.yaml`. |
| `CODEFLUX_DATABASE_URL` | SQLAlchemy async database URL. |
| `CODEFLUX_CREDENTIALS_JSON` | Optional provider credentials imported at gateway startup. |
| `CODEFLUX_HOST` / `CODEFLUX_PORT` | Gateway bind address and port. |
| `CODEFLUX_LOG_LEVEL` | Structured-log level. |

There are two distinct types of keys:

- A **CodeFlux client key** authenticates an application or teammate to the gateway.
- A **provider key** lets the gateway call OpenAI, Gemini, Groq, OpenRouter, or another upstream service.

Client keys must never be confused with provider keys. Clients receive CodeFlux keys only; provider keys stay inside the encrypted pool.

### Route configuration

`config/routes.yaml` maps stable aliases such as `gpt-4-tier` to ordered candidate models. Applications request an alias instead of depending directly on a provider model name.

A route can configure:

- `strategy`: `priority`, `round-robin`, `least-latency`, or `weighted-random`.
- `candidates`: provider/model pairs, preferred credential references, weights, and timeouts.
- `total_timeout_seconds`: deadline across all attempts.
- `allowed_teams`: optional route access list.
- `pii_redaction`: whether prompts are redacted before leaving CodeFlux.
- `ollama_fallback_model`: optional local fallback.

The preferred `api_key_ref` is a seed preference, not an exclusive key. Other contributed keys for that provider remain eligible.

## 5. Startup lifecycle

`codeflux/app.py` creates the FastAPI application. During its lifespan startup it:

1. Loads and validates `routes.yaml`.
2. Creates the async SQLAlchemy engine.
3. Creates missing database tables.
4. Creates the encrypted credential vault.
5. Imports any credentials supplied in `CODEFLUX_CREDENTIALS_JSON`.
6. Creates one shared async HTTP client.
7. Builds the provider adapter registry.
8. Creates the circuit breaker and provider-key pool.
9. Creates usage and managed-client-key repositories.
10. Builds the routing engine and stores shared services on `app.state`.

On shutdown, CodeFlux closes the HTTP client and database engine.

## 6. Authentication and team access

Clients send either:

```http
Authorization: Bearer <codeflux-key>
```

or:

```http
X-API-Key: <codeflux-key>
```

`codeflux/auth.py` supports two sources.

### Bootstrap keys

Bootstrap keys come from `CODEFLUX_GATEWAY_KEYS`, for example:

```dotenv
CODEFLUX_GATEWAY_KEYS=admin-bootstrap-key:admin,demo-key:demo
```

They are useful for initial administration and recovery. They do not have a managed monthly budget.

### Managed teammate keys

An administrator creates these in the **Team access** dashboard tab. A generated key starts with `cf_`. CodeFlux shows it once and stores only an HMAC-SHA256 digest derived with the master secret.

Each managed record contains:

- member/key name;
- team;
- non-secret prefix for identification;
- HMAC digest;
- optional monthly token limit;
- active status;
- creation and last-used timestamps.

On every managed-key request, CodeFlux calculates the team's usage since the first day of the current UTC month. If usage is already at or above that key's limit, authentication returns HTTP 429 before contacting a provider.

The budget is attached to the managed key, while consumption is aggregated by team. If multiple keys share a team but have different limits, each key compares the same team total against its own configured limit.

## 7. Provider credential vault and key pool

Provider secrets are handled by `CredentialVault` in `codeflux/storage.py`.

### Encryption at rest

1. CodeFlux hashes `CODEFLUX_MASTER_SECRET` with SHA-256.
2. The digest is URL-safe base64 encoded as a Fernet key.
3. The provider key is encrypted with Fernet.
4. SQLite stores only the encrypted ciphertext, reference, provider, and timestamp.

Fernet provides authenticated symmetric encryption. If the master secret changes, old ciphertext cannot be decrypted.

### Selection

`KeyPool` asks the vault for all credential references belonging to a provider. It creates in-memory state for each reference and selects the least recently used eligible key.

When a response contains supported headers such as:

- `x-ratelimit-remaining-requests`
- `x-ratelimit-reset-requests`

the pool records the request count and reset time. A key reporting zero remaining requests is temporarily skipped until reset.

This state is in memory. It resets when the gateway restarts and is not shared between multiple gateway instances.

## 8. Complete request lifecycle

Consider an OpenAI-compatible call to `/v1/chat/completions`.

### Step 1: Authenticate

The FastAPI dependency extracts the CodeFlux key, finds its team, checks a managed budget when applicable, and rejects invalid keys with HTTP 401.

### Step 2: Parse and normalize

`codeflux/normalization.py` converts OpenAI or Gemini payloads into `NormalizedRequest`. The routing engine therefore works with one representation for messages, prompts, embedding input, generation parameters, tools, and stream mode.

Malformed payloads return HTTP 422.

### Step 3: Resolve the logical route

The request's `model` is treated as a CodeFlux route alias. The engine finds it in `routes.yaml` and checks `allowed_teams` when configured.

### Step 4: Redact when enabled

If the route enables `pii_redaction`, the normalized request passes through `PIIRedactor` before it is sent externally.

### Step 5: Order candidates

The route strategy determines candidate order:

- `priority`: declared YAML order.
- `round-robin`: rotates the starting candidate per request.
- `least-latency`: sorts by recent in-memory latency observations.
- `weighted-random`: randomly selects candidates according to configured weights without repeating one in the same request.

An Ollama candidate is appended when a fallback model is configured and Ollama is not already listed.

### Step 6: Select a provider key

For each candidate, the key pool chooses an eligible encrypted provider credential and decrypts it in memory. Ollama can operate without an API key.

If no usable key exists, the attempt is marked `no-key` and routing continues.

### Step 7: Check the circuit

Circuit identity is `provider:key-reference`. After repeated failures, the circuit opens and requests skip that provider/key identity during the cooldown period. A later trial determines whether it recovers.

### Step 8: Call the provider

The adapter converts the normalized request into the provider's wire format and calls it through the shared `httpx.AsyncClient`. Candidate timeouts are bounded by the route's remaining overall deadline.

### Step 9: Handle success or failure

On success, CodeFlux:

- updates observed provider rate-limit state;
- closes/reset the circuit;
- records request, latency, and token metrics;
- writes usage to SQLite;
- stores last-route information for the dashboard;
- converts the result to OpenAI or Gemini response format.

On failure, it:

- increments the circuit failure count;
- records failover metrics and a structured warning;
- tries the next candidate while time remains.

If every candidate fails, CodeFlux returns HTTP 503 with `provider_unavailable` details.

## 9. Streaming behavior

OpenAI-compatible streaming responses are returned as Server-Sent Events and terminate with `data: [DONE]`.

The OpenAI-compatible adapter requests `stream_options.include_usage`. When the provider supplies a final usage block, the router records prompt and completion tokens after the stream finishes. Gemini's current adapter obtains a complete Gemini response and yields it as one stream chunk with its usage.

Not every OpenAI-compatible provider honors stream usage options. If a provider omits stream usage, CodeFlux cannot record exact tokens for that stream and does not invent an estimate.

Pre-stream failover is supported: CodeFlux obtains the first chunk before returning the selected stream. Failures after bytes have already been delivered cannot safely be replaced with a different provider response.

## 10. Token tracking and “tokens left”

Every successful response with provider-reported usage creates a `usage_records` row containing:

- timestamp;
- authenticated team;
- provider and provider-key reference;
- actual upstream model;
- request count;
- prompt tokens;
- completion tokens;
- estimated cost, currently defaulting to zero.

The dashboard and `/v1/usage` calculate totals from these records. `/v1/me` returns current-team usage since the beginning of the UTC calendar month.

For a managed key:

```text
tokens left = configured monthly token limit - team tokens used this UTC month
```

The result never goes below zero.

Important distinctions:

- **CodeFlux tokens left** means remaining internal budget for a managed key.
- **Provider request limit** means a value learned from provider response headers.
- **Provider billing credit or account token balance** is not known unless that provider explicitly exposes and CodeFlux integrates such an API.

Consequently, “Unknown” provider quota does not mean unlimited.

## 11. API surface

| Endpoint | Authentication | Behavior |
|---|---|---|
| `GET /health` | None | Basic gateway liveness. |
| `GET /health/providers` | CodeFlux key | Provider health checks and circuit snapshot. |
| `GET /v1/models` | CodeFlux key | Logical routes allowed for the team. |
| `GET /v1/me` | CodeFlux key | Identity, monthly limit, used, and remaining tokens. |
| `GET /v1/usage` | CodeFlux key | Usage summary scoped to the authenticated team. |
| `POST /v1/chat/completions` | CodeFlux key | OpenAI-compatible chat, including SSE. |
| `POST /v1/completions` | CodeFlux key | OpenAI-compatible completion. |
| `POST /v1/embeddings` | CodeFlux key | OpenAI-compatible embeddings. |
| `POST /v1beta/models/{model}:generateContent` | CodeFlux key | Gemini-compatible generation using a route alias. |
| `GET /metrics` | CodeFlux key | Prometheus text metrics. |
| `GET /dashboard/status` | CodeFlux key | Last route, observed limits, and circuits. |

## 12. Streamlit control room

The control room has four tabs.

### Overview

Shows gateway connectivity, last provider/model, request and token totals, provider limit observations, circuits, and—for the admin team—usage grouped by team.

### Work planner

Turns a master prompt into an ordered checklist by calling CodeFlux. The workflow, checklist completion, and latest result persist in SQLite. Clicking **Do the work** sends the original goal plus current checklist state through the selected route.

Workflows are currently shared database records, not team-scoped records. Anyone who can enter the protected dashboard can see them.

### Quota pool

Allows a user with a valid CodeFlux key to contribute a provider key. The UI generates a non-secret reference, encrypts the secret, and lists metadata without revealing plaintext.

Provider credentials form a shared pool. All gateway users whose routes reach that provider may consume them; they are not restricted to the contributor's team.

### Team access

Members see their team usage and connection variables. A user authenticated as team `admin` can generate managed teammate keys and inspect their metadata, monthly use, and remaining budget.

The current UI contains a shared `CODEFLUX_DASHBOARD_PASSWORD` outer gate plus the personal CodeFlux API key in the sidebar. The shared password is not a full identity system; production internet-facing deployments should use OIDC/SSO.

## 13. Database model

By default, CodeFlux uses SQLite through SQLAlchemy's async engine.

| Table | Contents |
|---|---|
| `credentials` | Encrypted provider keys and provider/reference metadata. |
| `client_api_keys` | Managed client-key HMAC digests, teams, budgets, and status. |
| `usage_records` | Team/provider/model token usage per request. |
| `workflows` | Planner title, master prompt, status, and latest result. |
| `checklist_items` | Ordered workflow items and completion state. |

`Base.metadata.create_all()` creates missing tables at startup. It is not a general schema migration system; future column changes should use a migration tool such as Alembic.

## 14. Circuit breaking and failover

Circuit state is tracked per provider-key identity, not only per provider. This prevents one failing credential from unnecessarily disabling every credential for that provider.

The configured `failure_threshold` opens a circuit after consecutive failures. `cooldown_seconds` determines when it may be tried again. Successful calls reset it.

Failover is candidate-based. It protects against missing keys, open circuits, timeouts, transport errors, provider errors, and rate-limit responses handled as adapter failures. It cannot guarantee recovery if every candidate is unavailable or incorrectly configured.

## 15. Observability

Prometheus metrics include:

- `codeflux_requests_total` by route, provider, and status;
- `codeflux_provider_latency_seconds` by provider;
- `codeflux_failovers_total` by provider and reason;
- `codeflux_circuit_open` by provider-key identity;
- `codeflux_tokens_total` by provider, token kind, and provider-key reference.

The logging setup emits structured records for completed requests, missing keys, provider failures, latency, attempts, and team attribution.

Prometheus counters and circuit state are process-local. Restarting the process resets them, although historical usage remains in SQLite.

## 16. Security model

Current protections include:

- encrypted provider secrets at rest;
- one-way managed client-key digests;
- constant-time comparison for bootstrap keys and the dashboard password;
- separation between client and provider credentials;
- optional route-level PII redaction;
- no plaintext provider-key listing endpoint;
- `.env` excluded from Git.

Operational requirements still matter:

- Use HTTPS; bearer keys are reusable credentials.
- Use strong, random bootstrap keys, dashboard password, and master secret.
- Share generated keys through a password manager.
- Restrict server and database access.
- Back up the database and master secret together.
- Rotate or revoke credentials after suspected exposure.
- Use OIDC/SSO and a real authorization model for a broad production rollout.

PII redaction is regex based and cannot guarantee removal of every sensitive value. Treat it as defense in depth, not a data-loss-prevention guarantee.

## 17. Docker deployment

Docker Compose starts:

- `codeflux`: FastAPI gateway;
- `dashboard`: Streamlit control room;
- `redis`: provisioned infrastructure;
- `ollama`: local model server.

The gateway and dashboard mount the same `./data` directory so both see the same SQLite file. The configuration directory is mounted read-only.

Redis is currently not used by the Python gateway. It is available for future distributed rate-limit, cache, or circuit state, but starting Redis does not make the current gateway horizontally distributed.

For Ollama inside Compose, its provider base URL must be `http://ollama:11434/v1`. For a gateway running directly on the host with host Ollama, it is normally `http://localhost:11434/v1`.

## 18. Scaling and current limitations

The current design is appropriate for one CodeFlux gateway instance and a small team. Important limitations are:

- SQLite is a single-host database and should not be placed on a shared network filesystem.
- Circuit, LRU, latency, and observed rate-limit state are in memory.
- Workflows and provider keys are shared globally rather than team-owned.
- Managed-key revocation exists in storage but is not yet exposed as a dashboard action.
- Exact usage depends on provider-reported token counts, especially for streams.
- Provider billing balances are not queried.
- Cost fields exist but model pricing and cost calculation are not implemented.
- The dashboard uses a shared password rather than native OIDC identity.
- Redis is not integrated into runtime state.

A multi-instance production version should use PostgreSQL, distributed state in Redis or another shared store, database migrations, OIDC, team-scoped resources, audit logs, and a reverse proxy with TLS.

## 19. Testing

The test suite covers normalization, provider-key rotation, failover, circuits, workflow persistence, managed client-key hashing/authentication, and basic Streamlit rendering.

Run it with:

```powershell
pytest -q
python -m ruff check codeflux streamlit_app.py tests
```

## 20. Practical end-to-end example

1. The owner starts the gateway and dashboard with an `admin` bootstrap key.
2. The owner adds a Gemini provider credential to the encrypted pool.
3. In **Team access**, the owner creates a key for Alice on team `engineering` with a 500,000-token monthly budget.
4. Alice configures an OpenAI SDK with the CodeFlux `/v1` base URL and her `cf_...` key.
5. Her application requests model `gemini-tier`.
6. CodeFlux authenticates Alice's key, checks the engineering team's month-to-date usage, and resolves the route.
7. The router selects the Gemini candidate and least-recently-used Gemini provider credential.
8. If that call fails, the route tries its next Gemini model, then OpenAI, OpenRouter, and finally configured Ollama fallback while the deadline allows.
9. CodeFlux returns an OpenAI-compatible response even if Gemini answered it.
10. Provider-reported prompt and completion tokens are stored against team `engineering` and reduce the remaining CodeFlux monthly budget shown to Alice.

That separation is the core of CodeFlux: applications depend on a stable team gateway, while providers, credentials, routing, failover, and usage policy stay centralized.
