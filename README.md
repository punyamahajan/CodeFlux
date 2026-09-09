# CodeFlux ⚡

CodeFlux is a self-hosted multi-provider AI gateway and Streamlit control room. Applications call one OpenAI- or Gemini-compatible API while CodeFlux selects an upstream model, rotates a shared pool of encrypted credentials, and automatically fails over when a provider times out, rate-limits, or exhausts its quota.

The control room adds a persistent, provider-independent **Work Planner**. A user enters a master prompt, an AI converts it into an actionable checklist, people can edit steps and mark progress, and **Do the work** executes against the current checklist state. Because progress is stored in SQLite instead of one provider's chat history, any subsequent provider can continue without losing context when a previous provider's quota is exhausted.

---

## What Works Now

- **Universal API compatibility**: OpenAI-compatible chat completions (`/v1/chat/completions`), embeddings, legacy completions, models listing, and SSE streaming, plus native Gemini `generateContent`.
- **Intelligent multi-candidate failover**: Cascades across providers (e.g. OpenAI → Gemini → Groq → local Ollama) with overall request deadline enforcement.
- **Quota pool with LRU rotation**: Multiple contributors can add API keys for any provider. Keys are rotated by least-recently-used (LRU) order, and keys with observed rate limits (`x-ratelimit-*`) are automatically paused until their reported reset time.
- **Zero-plaintext security**: All provider keys are encrypted at rest using AES (Fernet symmetric encryption) derived from your master secret. Plaintext keys are never shown again or leaked to clients.
- **Client key authentication**: External clients use Gateway Keys (`CODEFLUX_GATEWAY_KEYS`), completely shielding your upstream provider API keys.
- **In-memory circuit breakers**: Prevents cascading failures by opening circuits on consecutive provider errors and attempting half-open recovery after a cooldown.
- **Prometheus telemetry & structured logs**: Real-time metrics at `/metrics` and structured JSON logs.
- **Streamlit control room**: Dashboard showing live gateway status, circuit states, observed rate limits, and token usage, plus the persistent work planner and encrypted quota pool.

---

## Current Logical Routes

Routes are defined in [`config/routes.yaml`](config/routes.yaml):

| Route Alias | Strategy | Active Candidates & Failover Order |
| :--- | :--- | :--- |
| `gpt-4-tier` | Priority | 1. OpenAI `gpt-4o-mini`<br>2. Gemini `gemini-3.1-flash-lite`<br>3. Gemini `gemini-flash-latest`<br>4. Groq `llama-3.3-70b-versatile`<br>5. Ollama `llama3.2` *(fallback)* |
| `gemini-tier` | Priority | 1. Gemini `gemini-3.1-flash-lite`<br>2. Gemini `gemini-flash-latest`<br>3. OpenAI `gpt-4o-mini`<br>4. OpenRouter `google/gemini-2.0-flash-001`<br>5. Ollama `llama3.2` *(fallback)* |
| `embeddings` | Round-robin | 1. OpenAI `text-embedding-3-small` |

---

## 🚀 How to Start the Project (Step-by-Step Plan)

### Prerequisites
- **Python 3.10+** installed
- **Git** installed
- An API key from **Google AI Studio** (Gemini), **OpenAI**, or **Groq** (or a local **Ollama** instance)

---

### Step 1: Clone and Set Up Virtual Environment

```powershell
# Navigate into the project folder
cd CodeFlux

# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# On macOS / Linux:
# source .venv/bin/activate

# Upgrade pip and install dependencies in editable mode
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

---

### Step 2: Configure Environment Variables

Create your `.env` file from the provided example:

```powershell
Copy-Item .env.example .env
```

Ensure your `.env` contains:

```dotenv
# Secret used to encrypt/decrypt pooled API keys in SQLite (keep this stable between runs!)
CODEFLUX_MASTER_SECRET=replace-with-a-long-random-and-stable-secret

# Client keys for accessing the gateway (Format: <key>:<team>)
CODEFLUX_GATEWAY_KEYS=demo-key:demo,admin-key:admin

# Password to log into the Streamlit dashboard
CODEFLUX_DASHBOARD_PASSWORD=Punya@1806

# Path to routes and SQLite database
CODEFLUX_CONFIG_PATH=config/routes.yaml
CODEFLUX_DATABASE_URL=sqlite+aiosqlite:///./data/codeflux.db

# Host and port for the FastAPI gateway
CODEFLUX_HOST=0.0.0.0
CODEFLUX_PORT=8000
```

> ⚠️ **Important**: Keep `CODEFLUX_MASTER_SECRET` stable. If you change this secret after adding keys, previously encrypted keys cannot be decrypted.

---

### Step 3: Start the Backend Gateway

In **Terminal 1** (with `.venv` activated):

```powershell
python -m codeflux
```

The gateway starts on **`http://localhost:8000`**.
- OpenAPI Docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`
- Live metrics: `http://localhost:8000/metrics`

---

### Step 4: Start the Streamlit Control Room

In **Terminal 2** (with `.venv` activated):

```powershell
streamlit run streamlit_app.py
```

The dashboard opens in your browser at **`http://localhost:8501`**.

---

### Step 5: Add Provider API Keys to the Quota Pool

1. In the dashboard, click the **Quota pool** tab.
2. Under **Contribute a provider key**:
   - **Contributor name**: your name (e.g. `punya`)
   - **Provider**: select `gemini` or `openai`
   - **Provider API key**: paste your raw key
3. Click **Encrypt and add to pool**.
   - The key is immediately encrypted into `data/codeflux.db`.
   - The plaintext is never stored or shown again.
   - You can add multiple keys for the same provider to expand your daily quota!

---

### Step 6: Test Your Gateway Key (`demo-key`)

You can test that your gateway key works using PowerShell, Python, or curl:

#### Via PowerShell:
```powershell
$headers = @{
    Authorization = "Bearer demo-key"
    "Content-Type" = "application/json"
}
$body = @{
    model = "gemini-tier"
    messages = @(
        @{ role = "user"; content = "Say hello from CodeFlux!" }
    )
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/v1/chat/completions" -Method Post -Headers $headers -Body $body
```

#### Via Python (`openai` SDK):
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="demo-key",
)

response = client.chat.completions.create(
    model="gemini-tier",  # or "gpt-4-tier"
    messages=[{"role": "user", "content": "Explain CodeFlux in one sentence."}],
)
print(response.choices[0].message.content)
```

---

## 🐳 Docker Setup (Alternative to Local)

To run the entire stack (Gateway, Dashboard, Redis, and Ollama) in Docker containers:

```powershell
# Build and start all services
docker compose up --build -d

# (Optional) Download the local offline model in Ollama
docker compose exec ollama ollama pull llama3.2

# Check status
docker compose ps
```

- Open Dashboard: `http://localhost:8501`
- Open API Docs: `http://localhost:8000/docs`
- Stop containers: `docker compose down`

---

## 📋 Using the Persistent Work Planner

1. Open **`http://localhost:8501`** and go to the **Work planner** tab.
2. In the sidebar under **Connection**, select an **AI route** (e.g. `gemini-tier` or `gpt-4-tier`).
3. Enter a **Project title** and a detailed **Master prompt**.
4. Click **Generate checklist**: CodeFlux routes the request to an AI to produce a structured checklist.
5. Check off items as you complete them, or add new manual items.
6. Click **Do the work**: CodeFlux sends the original request along with the persisted checklist progress to produce the deliverable. If one provider runs out of quota, failover automatically hands the context to the next provider.

---

## 🧪 Running Tests

To run the full automated test suite (covering request normalization, LRU key pool rotation, failover logic, circuit breakers, and workflows):

```powershell
pytest -q
```

---

## 🔍 Troubleshooting & FAQ

### 1. `503 Service Unavailable: all providers failed`
- **Cause A (Key Selection)**: Verify your keys are in the **Quota pool** tab and that your chosen route has a provider you provided keys for.
- **Cause B (Quota Exhausted)**: If OpenAI returns `429 insufficient_quota`, CodeFlux will automatically fail over to Gemini as long as you have added a Gemini key.
- **Cause C (Deprecated Model)**: Google frequently updates model names. Ensure `config/routes.yaml` uses active models like `gemini-3.1-flash-lite` or `gemini-flash-latest` rather than deprecated versions.

### 2. `InvalidToken / Decryption Failure`
- **Cause**: If you modify `CODEFLUX_MASTER_SECRET` in `.env` after adding keys, the existing database cannot decrypt them. Delete the old database file at `data/codeflux.db` and re-add your keys.

### 3. Port 8000 Conflict
- If port 8000 is already in use by a background Docker container or previous process:
  ```powershell
  # Check what process is on port 8000
  Get-NetTCPConnection -LocalPort 8000
  # Stop the Docker container if needed
  docker stop codeflux-codeflux-1
  ```

---

## 📖 Deep Dive Architecture

For a comprehensive explanation of every component, request flows, encryption details, and tech stack choices, see **[`explain.md`](explain.md)**.
