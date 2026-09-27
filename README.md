# CodeFlux

CodeFlux is a self-hosted AI gateway and team control room. Your applications call one OpenAI-compatible API while CodeFlux chooses an upstream provider, rotates encrypted provider credentials, fails over when a provider is unavailable, and records token usage by team.

The Streamlit control room lets teammates contribute provider keys, view usage, receive personal CodeFlux API keys with monthly budgets, and manage persistent AI-assisted work checklists.

## Project overview

```text
Application / teammate
        |
        | CodeFlux API key
        v
FastAPI gateway :8000
        |
        +-- authenticate team and enforce monthly budget
        +-- normalize OpenAI or Gemini requests
        +-- select route, provider, and encrypted provider key
        +-- fail over across candidates when necessary
        +-- record usage in SQLite
        |
        v
OpenAI / Gemini / Groq / OpenRouter / Ollama

Streamlit control room :8501 ---> same SQLite database
```

Main capabilities:

- OpenAI-compatible chat, completion, embedding, model-listing, and streaming endpoints.
- Native Gemini `generateContent` endpoint.
- Priority, round-robin, least-latency, and weighted-random routing.
- Automatic provider failover and per-provider-key circuit breakers.
- Encrypted shared provider-key pool with least-recently-used rotation.
- Bootstrap gateway keys from `.env` and managed `cf_...` teammate keys stored as HMAC digests.
- Per-team prompt, completion, total, and calendar-month token tracking.
- Optional monthly token budgets for managed keys.
- Prometheus metrics, structured logs, and a persistent work planner.

For the complete architecture and request lifecycle, see [explain.md](explain.md).

## Requirements

- Python 3.10 or newer
- Git
- At least one supported provider API key, or a local Ollama installation
- Docker Desktop only if you prefer Docker Compose

## Start locally

### 1. Create the environment

```powershell
git clone <your-repository-url>
cd CodeFlux
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

On macOS or Linux, activate with `source .venv/bin/activate`.

### 2. Create the configuration

```powershell
Copy-Item .env.example .env
```

Edit `.env` and replace every placeholder secret:

```dotenv
CODEFLUX_MASTER_SECRET=generate-a-long-random-and-stable-secret
CODEFLUX_GATEWAY_KEYS=admin-bootstrap-key:admin
CODEFLUX_DASHBOARD_PASSWORD=choose-a-strong-dashboard-password
CODEFLUX_DASHBOARD_GATEWAY_URL=http://localhost:8000
CODEFLUX_CONFIG_PATH=config/routes.yaml
CODEFLUX_DATABASE_URL=sqlite+aiosqlite:///./data/codeflux.db
CODEFLUX_CREDENTIALS_JSON={}
CODEFLUX_HOST=0.0.0.0
CODEFLUX_PORT=8000
```

Keep `CODEFLUX_MASTER_SECRET` stable and backed up. Changing it makes previously stored provider credentials impossible to decrypt.

### 3. Start the gateway

Open the first terminal, activate the virtual environment, and run:

```powershell
python -m codeflux
```

Available URLs:

- Gateway: `http://localhost:8000`
- Health: `http://localhost:8000/health`
- OpenAPI documentation: `http://localhost:8000/docs`
- Prometheus metrics: `http://localhost:8000/metrics`

### 4. Start the control room

Open a second terminal, activate the same environment, and run:

```powershell
streamlit run streamlit_app.py --server.address 0.0.0.0
```

Open `http://localhost:8501`, enter the dashboard password, then put the admin bootstrap key from `CODEFLUX_GATEWAY_KEYS` (`admin-key`) into the sidebar.

### 5. Add a provider key

1. Open **Quota pool**.
2. Enter a contributor name.
3. Select a provider such as `gemini`, `openai`, or `groq`.
4. Paste the provider API key and select **Encrypt and add to pool**.

The provider key is encrypted before it is stored in `data/codeflux.db`. CodeFlux displays only its reference afterward.

### 6. Test the API

```powershell
$headers = @{
    Authorization = "Bearer admin-bootstrap-key"
    "Content-Type" = "application/json"
}
$body = @{
    model = "gemini-tier"
    messages = @(
        @{ role = "user"; content = "Say hello from CodeFlux." }
    )
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
    -Uri "http://localhost:8000/v1/chat/completions" `
    -Method Post `
    -Headers $headers `
    -Body $body
```

OpenAI Python clients can use CodeFlux by setting `base_url`:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="admin-bootstrap-key",
)

response = client.chat.completions.create(
    model="gemini-tier",
    messages=[{"role": "user", "content": "Explain CodeFlux in one sentence."}],
)
print(response.choices[0].message.content)
```

## Add teammates & multi-laptop setup (Same Wi-Fi)

To collaborate with teammates across two or more laptops on the same Wi-Fi:

### 1. Laptop 1 (Host Server)
Your laptop acts as the shared server hosting the gateway, database, and control room:
1. Find your Wi-Fi IPv4 address:
   ```powershell
   (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "Wi-Fi").IPAddress
   ```
   *(e.g., `10.7.12.170` or `192.168.1.50`)*
2. Start the gateway and dashboard:
   ```powershell
   python -m codeflux
   streamlit run streamlit_app.py --server.address 0.0.0.0
   ```
3. Open `http://localhost:8501`, log in, and enter `admin-key` in the sidebar.
4. Go to **Team access** > **Create a personal CodeFlux key**:
   - Enter member name and team (e.g. `engineering`).
   - Click **Create CodeFlux key** and copy the generated `cf_...` key.
5. Share with your teammate:
   - Dashboard URL: `http://<YOUR_WIFI_IP>:8501`
   - Dashboard Password: (from your `.env`)
   - Their personal CodeFlux key: `cf_...`

### 2. Laptop 2 (Teammate)
The teammate does **not** need to run servers. They simply connect to the Host:
1. Connect to the same Wi-Fi network.
2. Open browser at `http://<HOST_WIFI_IP>:8501` and enter the dashboard password.
3. In the sidebar under **Connection**, enter their personal `cf_...` key.
4. Go to **Quota pool** > enter contributor name, select provider (e.g. `gemini`), paste their provider API key, and click **Encrypt and add to pool**.
5. Use CodeFlux in their local code / Python scripts:
   ```python
   from openai import OpenAI

   client = OpenAI(
       base_url="http://<HOST_WIFI_IP>:8000/v1",
       api_key="cf_...",  # Their CodeFlux key
   )

   response = client.chat.completions.create(
       model="gemini-tier",
       messages=[{"role": "user", "content": "Hello from teammate laptop!"}],
   )
   print(response.choices[0].message.content)
   ```

### Are both laptops kept up to date?
**Yes, 100% in real time.** All workflows, checklist progress, encrypted API keys, and token usage are stored in the single centralized SQLite database (`data/codeflux.db`) on the Host laptop. Whenever either teammate adds a key, checks off a task, or calls the API, both laptops immediately see the updated state.


## Start with Docker Compose

```powershell
Copy-Item .env.example .env
# Edit .env and replace all placeholder secrets first.
docker compose up --build -d
docker compose ps
```

Then open:

- Dashboard: `http://localhost:8501`
- API documentation: `http://localhost:8000/docs`

To use the Compose Ollama container as the fallback, change the `ollama` base URL in `config/routes.yaml` to `http://ollama:11434/v1`, restart the stack, and pull the configured model:

```powershell
docker compose exec ollama ollama pull llama3.2
docker compose restart codeflux
```

Stop the stack without deleting persisted volumes:

```powershell
docker compose down
```

## Useful API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Unauthenticated service health |
| `GET` | `/health/providers` | Provider and circuit health |
| `GET` | `/v1/models` | Routes available to the authenticated team |
| `GET` | `/v1/me` | Current team and monthly budget usage |
| `GET` | `/v1/usage` | Usage summary scoped to the authenticated team |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat |
| `POST` | `/v1/completions` | OpenAI-compatible legacy completion |
| `POST` | `/v1/embeddings` | OpenAI-compatible embeddings |
| `POST` | `/v1beta/models/{model}:generateContent` | Gemini-compatible generation |
| `GET` | `/metrics` | Prometheus metrics |

All endpoints except `/health` require `Authorization: Bearer <codeflux-key>` or `X-API-Key: <codeflux-key>`.

## Tests

```powershell
pytest -q
python -m ruff check codeflux streamlit_app.py tests
```

## Deployment notes

- Run CodeFlux on an always-on server or VM for team access.
- Put the gateway and dashboard behind HTTPS and a reverse proxy.
- Do not expose the SQLite file over a network filesystem.
- Back up both `data/codeflux.db` and `CODEFLUX_MASTER_SECRET`.
- Keep `.env` and `.streamlit/secrets.toml` out of source control.
- The current dashboard password is a shared outer gate. Use organizational OIDC/SSO before a broad internet-facing rollout.
- SQLite is appropriate for one CodeFlux instance. A multi-instance production deployment needs a shared database and distributed circuit/rate-limit state.

## Troubleshooting

### `401 invalid or missing CodeFlux API key`

Confirm the bearer key is either present in `CODEFLUX_GATEWAY_KEYS` or was created in **Team access** and has not been revoked.

### `429 monthly CodeFlux token budget exhausted`

The managed key's team has reached that key's configured monthly budget. An administrator must issue access with an appropriate budget.

### `503 all providers failed`

Confirm that the selected route has at least one provider with a valid key, that model names are current, and that Ollama is reachable if it is the fallback.

### Stored provider keys no longer work

If `CODEFLUX_MASTER_SECRET` changed, restore the original secret. Otherwise, remove the unusable database only if losing its stored workflows, usage, and credentials is acceptable, then add the keys again.
