# CodeFlux

CodeFlux is a self-hosted FastAPI gateway that presents one OpenAI- and Gemini-compatible API while routing calls across multiple LLM providers. It normalizes requests, chooses a configured candidate and transparently fails over when an upstream times out, rate-limits, or fails.

This implementation favors a small, readable architecture suitable for extension and study. It includes encrypted credentials, per-key circuit breakers, key rotation, SQLite usage records, Prometheus metrics, PII masking, team authorization, streaming, and Ollama fallback.

## Architecture

```text
OpenAI / Gemini client
          |
    FastAPI + auth
          |
  canonical normalization ---- optional PII redaction
          |
    routing engine
     /    |     \
 key pool circuit  strategy/latency
     \    |     /
   provider adapter registry
    /       |          \
 OpenAI   Gemini   OpenAI-compatible providers
          |
 usage SQLite + Prometheus + JSON logs
```

The registry includes OpenAI, Gemini, Groq, Mistral, Cohere, Together, OpenRouter, Perplexity, DeepSeek, Ollama, Azure OpenAI, Bedrock (via a compatibility bridge), xAI, Fireworks and NVIDIA. Services exposing the OpenAI wire format share one adapter. Native Gemini conversion lives separately.

## Run CodeFlux locally

### Prerequisites

- Python 3.10 or newer
- Git
- At least one upstream provider API key, such as OpenAI, Gemini, or Groq
- Docker Desktop only if you want to use the Docker setup

### 1. Open the project directory

```powershell
cd C:\path\to\CodeFlux
```

### 2. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run this in the current terminal and try again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install CodeFlux

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### 4. Create and configure `.env`

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS or Linux:

```bash
cp .env.example .env
```

Open `.env` and configure it. Credential reference names must match the `api_key_ref` values in `config/routes.yaml`.

```dotenv
CODEFLUX_MASTER_SECRET=replace-this-with-a-long-random-secret
CODEFLUX_GATEWAY_KEYS=demo-key:demo,admin-key:admin
CODEFLUX_CONFIG_PATH=config/routes.yaml
CODEFLUX_DATABASE_URL=sqlite+aiosqlite:///./data/codeflux.db
CODEFLUX_CREDENTIALS_JSON={"openai-primary":{"provider":"openai","key":"sk-your-openai-key"},"groq-primary":{"provider":"groq","key":"gsk-your-groq-key"},"gemini-primary":{"provider":"gemini","key":"your-gemini-key"}}
```

You do not need credentials for every provider. At least one candidate in the route you call must have a valid credential or a working Ollama instance. Keep the same master secret between restarts because changing it makes existing encrypted credentials unreadable. Never commit `.env`.

### 5. Review the routing configuration

Open `config/routes.yaml`. Clients send a logical route name such as `gpt-4-tier`; CodeFlux maps that name to native provider models. Ensure the route includes a provider whose key you configured.

### 6. Start the API

```powershell
python -m codeflux
```

CodeFlux starts at `http://localhost:8000`. Keep this terminal open. Swagger documentation is available at `http://localhost:8000/docs`.

### 7. Verify the server

Open another PowerShell terminal:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Expected response:

```json
{"status":"ok","service":"codeflux"}
```

List the available routes:

```powershell
Invoke-RestMethod `
  -Uri http://localhost:8000/v1/models `
  -Headers @{ Authorization = "Bearer demo-key" }
```

Send a chat request:

```powershell
$body = @{
  model = "gpt-4-tier"
  messages = @(
    @{ role = "user"; content = "Say hello from CodeFlux" }
  )
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/v1/chat/completions `
  -Headers @{ Authorization = "Bearer demo-key" } `
  -ContentType "application/json" `
  -Body $body
```

The bearer value is a gateway key from `CODEFLUX_GATEWAY_KEYS`, not an upstream provider key.

## Run with Docker, Redis, and Ollama

### 1. Create and edit `.env`

```powershell
Copy-Item .env.example .env
```

Add cloud credentials if desired. Ollama can act as the final fallback without an upstream API key.

### 2. Build and start the services

```powershell
docker compose up --build -d
```

### 3. Download the configured Ollama model

```powershell
docker compose exec ollama ollama pull llama3.2
```

The initial model download may take several minutes.

### 4. Check status and logs

```powershell
docker compose ps
docker compose logs -f codeflux
```

Press `Ctrl+C` to stop following logs; the containers remain running.

### 5. Stop the stack

```powershell
docker compose down
```

To perform a complete reset, including the database and downloaded models:

```powershell
docker compose down -v
```

The `-v` command permanently removes persisted Docker volumes. Redis is included for future distributed state support; the reference implementation currently keeps circuit and rate state in-process.

## Common startup problems

- `401 invalid or missing CodeFlux API key`: use a key from `CODEFLUX_GATEWAY_KEYS` in `Authorization: Bearer ...`.
- `all providers failed`: verify the route's `api_key_ref`, its matching `CODEFLUX_CREDENTIALS_JSON` entry, and the provider key.
- Ollama fails during a native Python run: change `provider_base_urls.ollama` in `config/routes.yaml` from `http://ollama:11434/v1` to `http://localhost:11434/v1`.
- Ollama model missing: run `ollama pull llama3.2` locally or use the Docker pull command above.
- Port 8000 is occupied: set `CODEFLUX_PORT=8001` in `.env` and use port 8001 in requests.
- Stored credentials cannot be decrypted: restore the original master secret or remove `data/codeflux.db` to create a fresh credential database.

## Calling the gateway

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer demo-key" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4-tier","messages":[{"role":"user","content":"Hello"}]}'
```

Set `"stream": true` for OpenAI SSE chunks. Gemini clients can call `POST /v1beta/models/gemini-tier:generateContent`. Other endpoints are `/v1/completions`, `/v1/embeddings`, `/v1/models`, `/health`, `/health/providers`, and `/metrics`. Health itself is public for container probes; detailed health and metrics require a gateway key.

## Routes and failover

Edit [config/routes.yaml](config/routes.yaml). A logical model alias owns a candidate list, overall timeout, strategy, optional allowed teams, PII toggle, and optional Ollama fallback. Supported strategies are:

- `priority`: configured order.
- `round-robin`: rotate the first candidate per request, retaining the rest for failover.
- `least-latency`: lowest rolling mean latency first; unseen providers are tried later.
- `weighted-random`: weighted sampling without replacement.

Each attempt selects the least-recently-used eligible key. Failures increment the provider+key circuit. At the threshold it opens; after cooldown exactly one half-open probe is allowed. A success closes it. Streaming can fail over until the first upstream chunk is received; once bytes reach the client, HTTP cannot transparently switch streams.

Routes with `allowed_teams` enforce lightweight RBAC. A gateway API key maps to a team through `CODEFLUX_GATEWAY_KEYS`. Upstream and gateway keys are separate.

## Adding a provider

If it implements the OpenAI API shape, add its name and base URL to `DEFAULT_BASE_URLS` in `codeflux/adapters/registry.py`, or set the URL under `provider_base_urls` in YAML and register it during app setup. For a native protocol:

1. Implement `ProviderAdapter` from `codeflux/adapters/base.py`.
2. Translate `NormalizedRequest` into the native payload and return `NormalizedResponse`.
3. Implement the streaming and health methods.
4. Register the instance in `AdapterRegistry` and add mocked conversion tests.

Azure deployments often require an `api-version` and deployment-specific URL; configure its base URL for your deployment. Direct Bedrock SigV4 is deliberately outside the small core—point `bedrock` to an OpenAI-compatible Bedrock bridge, or add a boto3-backed native adapter using the same contract.

## PII, accounting, and rate limits

Set `pii_redaction: true` on a route. With the `pii` extra installed, Presidio performs analysis/anonymization; otherwise a deterministic fallback masks email and card-like patterns. Responses are not un-redacted because generated text cannot safely be mapped to arbitrary originals.

Successful calls create usage rows with team, provider, key reference and token counts. Prometheus counters expose requests, errors, latency, failovers, tokens and circuits. Key state understands common `x-ratelimit-*` fields through `KeyPool.update_limits`; adapters can feed response headers into it as providers expose consistent formats. The in-memory state is intentionally replaceable with Redis for multiple replicas.

## Tests

```bash
pytest
```

Tests cover OpenAI/Gemini normalization, priority failover, circuit closed/open/half-open transitions, and LRU key rotation. All provider behavior is mocked; tests make no network calls.

## Project layout

```text
codeflux/
  adapters/       provider protocol, Gemini and OpenAI-compatible adapters
  app.py          HTTP endpoints and lifecycle wiring
  normalization.py canonical input/output conversion
  router.py       strategies, retry budget and failover
  circuit.py      per-provider+key state machine
  keys.py         rate-aware LRU key pool
  storage.py      encrypted credentials and usage persistence
  auth.py, pii.py, metrics.py
config/routes.yaml
tests/
```

## Assumptions and scope

- SQLite and one process are the default; interfaces are kept small so Postgres/Redis can replace local state.
- Cost defaults to zero because prices change frequently; populate a pricing table before using cost accounting for billing.
- Several vendors support only a subset of OpenAI operations, so route embeddings and legacy completions only to providers/models that actually expose them.
- Presidio, Redis, direct AWS credentials/KMS, and a graphical admin dashboard remain optional deployment extensions. Operational data is already available through health, metrics, logs and SQLite.
