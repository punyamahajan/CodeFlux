# OmniKey: 5-Minute Interactive Walkthrough

Welcome to **OmniKey** (package `codeflux`) — the unified AI gateway that pools upstream provider keys, issues budget-controlled platform keys to team members, automatically fails over with circuit breakers, and explains every decision with deterministic facts and AI narration.

---

## The Problem

1. **Vendor Lock-in & Brittle Upstreams**: When OpenAI throws a `429 Too Many Requests` or Anthropic experiences an outage, your production apps fail unless you write custom fallback adapters for every provider.
2. **Credential Sprawl & Runaway Spend**: Handing out raw provider API keys leads to leaked credentials, unbounded credit card usage, and zero auditability on who ran what prompt.
3. **Black-box Mystery**: When an AI request gets refused or costs $0.45 instead of $0.05, nobody knows why.

OmniKey solves all three with a drop-in proxy, double-entry ledger accounting, and a built-in Explain Engine.

---

## 1. Quickstart: Start the Gateway & Frontend

```bash
# 1. Start the backend gateway (FastAPI on :8000)
uvicorn codeflux.app:app --reload --port 8000

# 2. In another terminal, start the frontend (Vite dev server on :3000)
cd frontend && npm run dev
```

Visit `http://localhost:3000` (or `http://localhost:8000` in production).

---

## 2. Walkthrough Scenarios

### Step 1: Sign in with the Demo Admin Account
- Go to `http://localhost:3000/auth`
- Login with:
  - **Email**: `admin@omnikey.demo`
  - **Password**: `demopassword123`
- You are directed to `/admin` showing real-time stat cards (requests, tokens, spend, fallback rate, p95 latency) and model breakdown.

### Step 2: Inspect Encrypted Provider Key Vault
- Navigate to `/admin/vault`
- Notice credentials for OpenAI, Gemini, Groq, and Ollama.
- Provider secrets are AES-128-CBC / Fernet encrypted in PostgreSQL. Only the hint (last 4 characters) is ever exposed.

### Step 3: Issue a Limited Platform Key
- Navigate to `/admin/keys`
- Click **"Generate Platform Key"**
- Give it a name (e.g. `Mobile App Key`), set a credit limit of `$10.00`, and set `60 RPM`.
- Copy the newly generated key: `ok_live_...`
- Notice the **One-Time Reveal Dialog** with instant cURL and Python quickstart code snippets.

### Step 4: Make a Gateway Call via cURL
Run a chat completion through the gateway using your platform key:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer ok_live_demo_admin_secret_key_12345" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "smart",
    "messages": [{"role": "user", "content": "Explain the speed of light in one sentence."}]
  }'
```

Notice the response headers:
- `X-OmniKey-Trace-Id`: `trc_...`
- `X-OmniKey-Provider`: `openai` (or `gemini` / `groq`)
- `X-OmniKey-Attempts`: `1`
- `X-OmniKey-Latency-Ms`: `340`
- `X-OmniKey-Credits-Remaining`: `99996529`

### Step 5: Simulate an Outage & Experience Fallback
- Trigger an outage simulation on the primary candidate:
```bash
curl -X POST http://localhost:8000/demo/outage/openai
```
- Re-send the exact same cURL request:
- The request immediately succeeds with HTTP 200 from `gemini` or `groq`!
- Reset outage: `curl -X DELETE http://localhost:8000/demo/outage/openai`

### Step 6: Click the "Why?" Panel
- Navigate to `/admin/traces`
- Click the **"Why?"** badge beside the fallback trace.
- The **WhyPanel** drawer opens showing:
  - **Headline**: "Request succeeded via gemini/gemini-2.0-flash."
  - **Key Factors**: "A fallback occurred: 1 provider(s) failed before success. Candidate openai/gpt-4o-mini was skipped."
  - **AI Narration**: Click **"Explain with AI Narration"** to see an LLM-narrated explanation. If the LLM invents unverified numbers, the guard strictly rejects it and defaults to deterministic facts.

### Step 7: Continue Context in a Session
- Send two consecutive requests with session header:
```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer ok_live_demo_admin_secret_key_12345" \
  -H "X-OmniKey-Session: ses_demo_walkthrough_01" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "smart",
    "messages": [{"role": "user", "content": "My favorite fruit is Mango."}]
  }'

curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer ok_live_demo_admin_secret_key_12345" \
  -H "X-OmniKey-Session: ses_demo_walkthrough_01" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "smart",
    "messages": [{"role": "user", "content": "What is my favorite fruit?"}]
  }'
```
- The second response correctly knows your favorite fruit is Mango, even if the second request failed over to a different model.

### Step 8: Compare Arena
- Navigate to `/arena/compare`
- Enter prompt: `Explain the difference between TCP and UDP.`
- Select models: `gpt-4o-mini`, `gemini-2.0-flash`, `llama-3.3-70b-versatile`
- Check **"Enable AI Judge Evaluation"**
- Click **"Run Arena Comparison"**: all 3 models run in parallel with no fallback, receive accuracy, clarity, and completeness scores, and code calculates the deterministic ranking.

### Step 9: Debate Arena
- Navigate to `/arena/debate`
- Topic: `Should AI code generators be required to attribute their training data sources?`
- Side FOR: `gpt-4o-mini`
- Side AGAINST: `claude-3-haiku`
- Click **"Start Oxford Debate"**: models take alternating turns capped at 120 words, the judge evaluates argument strength, evidence, and rebuttal, and awards the final verdict.

### Step 10: Member Limit Increase & Approval
- Log out and log in as member: `alice@omnikey.demo` / `demopassword123`
- At `/app`, click **"Request Limit Increase"** from `$25` to `$50` with reason: `Running evaluation benchmark`.
- Log back in as `admin@omnikey.demo`, go to `/admin/requests`, and click **Approve**.
- Alice's key limit and ledger instantly update with double-entry integrity!
