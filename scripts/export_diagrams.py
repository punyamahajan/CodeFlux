import os
import base64
import urllib.request

os.makedirs('docs/diagrams', exist_ok=True)

diagrams = {
    'figure_2_1_system_context': """graph TD
    subgraph Clients["Downstream Consumers"]
        C1["Python / Node.js SDK Clients"]
        C2["IDE Coding Assistants (Cursor, VS Code)"]
        C3["Automated CI/CD Pipelines & Agents"]
    end

    subgraph Gateway["CodeFlux Gateway Perimeter (:8000)"]
        direction TB
        G1["Ingress Filter & CORS"]
        G2["Auth Guard<br/>(Constant-Time HMAC-SHA256)"]
        G3["Budget Engine<br/>(Calendar-Month Quota Gate)"]
        G4["Dynamic Router<br/>(Priority / Latency EMA / Round-Robin)"]
        G5["Per-Key Circuit Breaker<br/>(Threshold=3, Cooldown=30s)"]
        G6["Credential Vault<br/>(AES-128-CBC / Fernet with LRU Rotation)"]
        
        G1 --> G2
        G2 --> G3
        G3 --> G4
        G4 <--> G5
        G4 <--> G6
    end

    subgraph Providers["Upstream Model Providers"]
        P1[("OpenAI Cloud<br/>gpt-4o / gpt-4o-mini")]
        P2[("Google Gemini Cloud<br/>gemini-2.5-flash")]
        P3[("Groq Cloud<br/>llama-3.3-70b")]
        P4[("Localhost Daemon<br/>Ollama / qwen2.5-coder")]
    end

    Clients -- "HTTP POST /v1/chat/completions<br/>(Bearer cf_... or ok_live_...)" --> G1
    G4 -- "HTTPS (Restricted)" --> P1
    G4 -- "HTTPS (Restricted)" --> P2
    G4 -- "HTTPS (Restricted)" --> P3
    G4 -- "HTTP Local Fallback" --> P4

    classDef clientStyle fill:#EEF2FF,stroke:#6366F1,stroke-width:2px,color:#1E1B4B;
    classDef gwStyle fill:#F8FAFC,stroke:#475569,stroke-width:2px,color:#0F172A;
    classDef provStyle fill:#ECFDF5,stroke:#10B981,stroke-width:2px,color:#064E3B;
    class C1,C2,C3 clientStyle;
    class G1,G2,G3,G4,G5,G6 gwStyle;
    class P1,P2,P3,P4 provStyle;""",

    'figure_4_1_relational_schema': """erDiagram
    CREDENTIALS {
        string reference PK "Unique provider key handle"
        string provider "openai | gemini | groq | ollama"
        text encrypted_value "Fernet ciphertext (AES-128-CBC)"
        datetime created_at "Registration timestamp"
    }

    CLIENT_API_KEYS {
        int id PK "Auto-increment key ID"
        string name "Key label / environment"
        string team "Assigned tenant team"
        string key_prefix "First 11 characters (Display only)"
        string key_digest UK "Salted HMAC-SHA256 digest"
        bigint monthly_token_limit "Maximum token quota per month"
        boolean active "Active / Revoked flag"
        datetime last_used_at "Timestamp of last invocation"
    }

    WORKFLOWS {
        int id PK "Workflow ID"
        string title "Goal title"
        text master_prompt "High-level planning context"
        string status "pending | in_progress | completed"
        text result "Aggregated execution summary"
    }

    CHECKLIST_ITEMS {
        int id PK "Task ID"
        int workflow_id FK "Parent workflow reference"
        text text "Actionable item description"
        boolean completed "Boolean resolution flag"
        int position "Execution order sequence"
        string model_route "Target route alias"
    }

    USAGE_RECORDS {
        int id PK "Auto-increment ledger ID"
        datetime timestamp "UTC completion timestamp"
        string team "Associated tenant team"
        string provider "Fulfilling provider"
        string key_ref "Credential handle used"
        string model "Model invoked"
        int prompt_tokens "Input tokens billed"
        int completion_tokens "Output tokens billed"
        float estimated_cost "Calculated cost in USD"
    }

    WORKFLOWS ||--o{ CHECKLIST_ITEMS : "contains"
    CLIENT_API_KEYS ||--o{ USAGE_RECORDS : "tracks activity of"
    CREDENTIALS ||--o{ USAGE_RECORDS : "dispatched through" """,

    'figure_5_1_execution_pipeline': """sequenceDiagram
    autonumber
    actor Client as Client / IDE Agent
    participant Gateway as Ingress & Auth Guard
    participant Budget as Budget Evaluator
    participant Router as Routing Engine
    participant Breaker as Circuit Breaker Pool
    participant Vault as Key Vault (Fernet)
    participant Cloud as Cloud Provider (Groq / Gemini)
    participant Local as Local Model (Ollama)
    participant Ledger as Audit Ledger (DB)

    Client->>Gateway: POST /v1/chat/completions (Bearer cf_key)
    Gateway->>Gateway: HMAC-SHA256(secret, cf_key) == Digest
    
    Gateway->>Budget: Validate Month-to-Date Token Consumption
    alt Quota Exceeded (Usage >= Limit)
        Budget-->>Client: HTTP 429 Too Many Requests (Budget Exhausted)
    else Quota Available
        Budget->>Router: Forward Normalized Unified Payload
        
        Router->>Breaker: Check Candidate 1 (Primary Cloud)
        alt Circuit Open / Cooldown Active
            Breaker-->>Router: Candidate 1 Tripped (Skip)
        else Circuit Closed
            Router->>Vault: Fetch & Decrypt Primary Key (LRU)
            Vault-->>Router: Transient Plaintext Key
            Router->>Cloud: Dispatch Inbound Prompt (Timeout = 10s)
            Cloud-->>Router: HTTP 429 / HTTP 503 (Upstream Throttled)
            Router->>Breaker: Record Failure (FailCount += 1)
        end

        Note over Router,Local: Failover triggered: Routing Engine cascades to offline candidate
        
        Router->>Local: Dispatch Fallback Prompt (qwen2.5-coder)
        Local-->>Router: HTTP 200 OK + Generated Stream / Tokens
        
        Router->>Ledger: Insert Transaction (Tokens, Latency, Fallback Flags)
        Router-->>Client: HTTP 200 OK (OpenAI-compatible Response Body)
    end"""
}

headers = {'User-Agent': 'Mozilla/5.0'}

for name, code in diagrams.items():
    # 1. Save raw .mmd
    mmd_path = f'docs/diagrams/{name}.mmd'
    with open(mmd_path, 'w', encoding='utf-8') as f:
        f.write(code)
    print(f'[OK] Wrote {mmd_path}')

    # 2. Render SVG via mermaid.ink
    enc = base64.urlsafe_b64encode(code.strip().encode('utf-8')).decode('ascii')
    svg_url = f'https://mermaid.ink/svg/{enc}'
    png_url = f'https://mermaid.ink/img/{enc}?scale=2'

    try:
        req = urllib.request.Request(svg_url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            svg_data = r.read()
            svg_path = f'docs/diagrams/{name}.svg'
            with open(svg_path, 'wb') as out:
                out.write(svg_data)
        print(f'[OK] Downloaded {svg_path} ({len(svg_data)} bytes)')
    except Exception as e:
        print(f'[ERROR] SVG for {name}: {e}')

    try:
        req = urllib.request.Request(png_url, headers=headers)
        with urllib.request.urlopen(req, timeout=25) as r:
            png_data = r.read()
            png_path = f'docs/diagrams/{name}.png'
            with open(png_path, 'wb') as out:
                out.write(png_data)
        print(f'[OK] Downloaded {png_path} ({len(png_data)} bytes)')
    except Exception as e:
        print(f'[ERROR] PNG for {name}: {e}')

print('All exports processed!')
