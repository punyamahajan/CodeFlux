from __future__ import annotations

import asyncio
import json
import os
import threading
import time

import httpx
import openai
import uvicorn
from dotenv import load_dotenv
from openai import OpenAI

from codeflux.app import create_app
from codeflux.db.models import Organization, PlatformKey, User
from codeflux.db.session import Database
from codeflux.security.crypto import generate_platform_key, hash_platform_key
from codeflux.settings import Settings


def main() -> None:
    load_dotenv()
    database_url = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://postgres:password@127.0.0.1:5432/omnikey_test"
    )
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_key:
        raise ValueError("GROQ_API_KEY is not set in .env")

    print("[1/5] Setting up test credentials and database record...")
    settings = Settings(
        database_url=database_url,
        env="dev",
        credentials_json=json.dumps({"groq-primary": {"provider": "groq", "key": groq_key}}),
    )

    # 1. Create Org, User, and PlatformKey in PostgreSQL
    async def create_fixture() -> str:
        db = Database(database_url)
        raw_key = generate_platform_key()
        digest = hash_platform_key(raw_key, settings.key_hmac_secret)

        async with db.sessions() as session:
            org = Organization(name="Smoke Test Org")
            session.add(org)
            await session.flush()

            user = User(
                org_id=org.id,
                email="smoketest@example.com",
                password_hash="argon2_fake",
                role="admin",
            )
            session.add(user)
            await session.flush()

            key = PlatformKey(
                org_id=org.id,
                user_id=user.id,
                name="Smoke Test Key",
                key_prefix=raw_key[:16],
                key_digest=digest,
                credit_limit_micro=50_000_000,
                credit_remaining_micro=50_000_000,
                rpm_limit=60,
            )
            session.add(key)
            await session.commit()

        await db.close()
        return raw_key

    raw_platform_key = asyncio.run(create_fixture())
    print(f"[2/5] Created platform key: {raw_platform_key[:16]}...")

    # 2. Start Uvicorn in background thread
    app = create_app(settings)
    config = uvicorn.Config(app=app, host="127.0.0.1", port=8000, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server ready
    ready = False
    for _ in range(50):
        try:
            r = httpx.get("http://127.0.0.1:8000/healthz", timeout=1.0)
            if r.status_code == 200:
                ready = True
                break
        except (httpx.HTTPError, OSError):
            time.sleep(0.1)

    if not ready:
        server.should_exit = True
        raise RuntimeError("Server failed to start on port 8000")

    print("[3/5] Gateway running at http://127.0.0.1:8000. Calling via OpenAI SDK...")

    # 3. Call official OpenAI SDK
    client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key=raw_platform_key)

    print("\n--- Non-Streaming Completion ---")
    completion = client.chat.completions.create(
        model="groq-tier",
        messages=[
            {"role": "system", "content": "You are a concise AI assistant."},
            {
                "role": "user",
                "content": "What is the capital of France? Answer in one short sentence.",
            },
        ],
    )
    print("Response ID:", completion.id)
    print("Model:", completion.model)
    print("Role:", completion.choices[0].message.role)
    print("Content:", completion.choices[0].message.content)
    print("Finish Reason:", completion.choices[0].finish_reason)
    if completion.usage:
        print(
            f"Usage: prompt_tokens={completion.usage.prompt_tokens}, completion_tokens={completion.usage.completion_tokens}, total_tokens={completion.usage.total_tokens}"
        )

    print("\n--- Streaming Completion ---")
    stream = client.chat.completions.create(
        model="groq-tier",
        messages=[
            {"role": "user", "content": "Count from 1 to 5 separated by commas."},
        ],
        stream=True,
    )
    print("Streamed chunks: ", end="", flush=True)
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)
    print("\n")

    print("[4/5] Testing Auth Rejection via OpenAI SDK...")
    bad_client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="ok_live_invalid_key_12345")
    try:
        bad_client.chat.completions.create(
            model="groq-tier",
            messages=[{"role": "user", "content": "Hi"}],
        )
        print("ERROR: Expected auth failure!")
    except openai.AuthenticationError as exc:
        print("Caught expected OpenAI SDK AuthenticationError:", type(exc).__name__, "-", exc)

    print("[5/5] Shutting down gateway server...")
    server.should_exit = True
    thread.join(timeout=3.0)
    print("Smoke test successfully completed!")


if __name__ == "__main__":
    main()
