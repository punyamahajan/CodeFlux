"""Comprehensive end-to-end integration and verification script for OmniKey."""

from __future__ import annotations

import asyncio
import logging

import httpx

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("e2e")

BASE_URL = "http://127.0.0.1:8000"


async def run_e2e():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=45.0) as client:
        # 1. Health check & Frontend SPA index
        logger.info("=== 1. Checking /health and SPA Frontend ===")
        r = await client.get("/health")
        assert r.status_code == 200, f"Health check failed: {r.status_code}"
        logger.info("✓ /health returned 200 OK: %s", r.json())

        r = await client.get("/")
        assert r.status_code == 200, f"Frontend root failed: {r.status_code}"
        assert "<html" in r.text.lower() or "<!doctype html>" in r.text.lower()
        logger.info("✓ Frontend SPA root (/) returned 200 HTML (%d bytes)", len(r.text))

        # Check an asset request
        if 'src="/assets/' in r.text:
            asset_path = r.text.split('src="')[1].split('"')[0]
            r_asset = await client.get(asset_path)
            assert r_asset.status_code == 200, f"Asset {asset_path} failed: {r_asset.status_code}"
            logger.info(
                "✓ Frontend bundle asset %s returned 200 (%d bytes)",
                asset_path,
                len(r_asset.content),
            )

        # 2. Authentication
        logger.info("\n=== 2. Testing Authentication (/api/auth/login) ===")
        login_res = await client.post(
            "/api/auth/login",
            json={"email": "admin@omnikey.demo", "password": "demopassword123"},
        )
        assert login_res.status_code == 200, (
            f"Login failed: {login_res.status_code} {login_res.text}"
        )
        auth_data = login_res.json()
        token = auth_data["token"]
        user = auth_data["user"]
        headers = {"Authorization": f"Bearer {token}"}
        logger.info("✓ Admin login successful. User: %s (%s)", user["email"], user["role"])

        # Test auth check (/api/auth/me)
        me_res = await client.get("/api/auth/me", headers=headers)
        assert me_res.status_code == 200
        logger.info("✓ /api/auth/me returned user record: %s", me_res.json()["email"])

        # 3. Admin Dashboard & Metrics
        logger.info("\n=== 3. Testing Admin Dashboard APIs ===")
        usage_res = await client.get("/api/admin/usage", headers=headers)
        assert usage_res.status_code == 200, f"Usage overview failed: {usage_res.status_code}"
        logger.info("✓ Usage overview: %s", usage_res.json())

        traces_res = await client.get("/api/admin/traces", headers=headers)
        assert traces_res.status_code == 200, f"Traces listing failed: {traces_res.status_code}"
        traces_list = traces_res.json()
        logger.info("✓ Traces API returned %d traces", len(traces_list))

        # 4. Vault Management
        logger.info("\n=== 4. Testing Vault (/api/admin/vault) ===")
        vault_res = await client.get("/api/admin/vault", headers=headers)
        assert vault_res.status_code == 200
        vault_items = vault_res.json()["items"]
        logger.info("✓ Vault contains %d credentials:", len(vault_items))
        for item in vault_items:
            logger.info(
                "   - Provider: %-8s | Hint: ...%-4s | Enabled: %s",
                item["provider"],
                item["key_hint"],
                item["enabled"],
            )

        # 5. Platform Key Generation and Live Gateway Verification
        logger.info("\n=== 5. Testing Platform Key Generation and Live Usage ===")
        create_key_res = await client.post(
            "/api/admin/keys",
            headers=headers,
            json={
                "name": "Live E2E Verification Key",
                "credit_limit_usd": 15.0,
                "rpm_limit": 60,
                "allowed_routes": ["fast", "smart", "code"],
            },
        )
        assert create_key_res.status_code == 201, f"Key generation failed: {create_key_res.text}"
        new_key_data = create_key_res.json()
        raw_key = new_key_data["raw_key"]
        key_id = new_key_data["id"]
        assert raw_key.startswith("ok_live_"), f"Unexpected key format: {raw_key}"
        logger.info(
            "✓ Successfully generated new Platform Key: %s (ID: %s)", raw_key[:16] + "...", key_id
        )

        # Now make an actual gateway call with this brand-new platform key!
        logger.info("--> Testing /v1/chat/completions using newly generated platform key...")
        gw_headers = {"Authorization": f"Bearer {raw_key}"}
        gw_payload = {
            "model": "fast",
            "messages": [
                {"role": "user", "content": "Reply with exact words: 'OmniKey Gateway Verified'"}
            ],
        }
        gw_res = await client.post("/v1/chat/completions", headers=gw_headers, json=gw_payload)
        assert gw_res.status_code == 200, (
            f"Gateway request with new key failed: {gw_res.status_code} {gw_res.text}"
        )
        gw_json = gw_res.json()
        reply_text = gw_json["choices"][0]["message"]["content"]
        trace_id = gw_res.headers.get("x-omnikey-trace-id")
        provider_used = gw_res.headers.get("x-omnikey-provider")
        credits_left = gw_res.headers.get("x-omnikey-credits-remaining")
        logger.info("✓ Gateway Response Received (200 OK):")
        logger.info("   - Provider: %s", provider_used)
        logger.info("   - Trace ID: %s", trace_id)
        logger.info("   - Credits Remaining: %s micro-USD", credits_left)
        logger.info("   - Reply: %s", reply_text.strip())

        # 6. Explainable AI & WhyPanel
        logger.info("\n=== 6. Testing Explainable AI Engine ===")
        assert trace_id, "No trace_id returned from gateway call"
        explain_res = await client.get(f"/api/explain/trace/{trace_id}", headers=headers)
        assert explain_res.status_code == 200, (
            f"Explain trace failed: {explain_res.status_code} {explain_res.text}"
        )
        explain_data = explain_res.json()
        logger.info("✓ Trace Explanation Headline: %s", explain_data["headline"])
        logger.info("✓ Trace Explanation Bullets:")
        for b in explain_data["bullets"]:
            logger.info("   • %s", b)

        # Test Narrate
        logger.info("--> Testing AI Narration with guard verification...")
        narrate_res = await client.post(f"/api/explain/trace/{trace_id}/narrate", headers=headers)
        assert narrate_res.status_code == 200, (
            f"Narrate failed: {narrate_res.status_code} {narrate_res.text}"
        )
        narrate_data = narrate_res.json()
        logger.info(
            "✓ AI Narration (%s): %s",
            "cached" if narrate_data.get("cached") else "generated",
            narrate_data["narration"][:160] + "...",
        )

        # 7. Routes Listing
        logger.info("\n=== 7. Testing Routes (/api/admin/routes) ===")
        routes_res = await client.get("/api/admin/routes", headers=headers)
        assert routes_res.status_code == 200
        routes_list = routes_res.json()["items"]
        logger.info("✓ Configured Routes (%d):", len(routes_list))
        for r in routes_list:
            cands = ", ".join(f"{c['provider']}:{c['model']}" for c in r["candidates"])
            logger.info("   - Route '%s' (%s) -> [%s]", r["alias"], r["strategy"], cands)

        # 8. Interactive Playground
        logger.info("\n=== 8. Testing Interactive Playground (/api/playground/chat) ===")
        play_res = await client.post(
            "/api/playground/chat",
            headers=headers,
            json={
                "format": "openai",
                "model": "fast",
                "messages": [{"role": "user", "content": "What is 2+2? Answer in one word."}],
            },
        )
        assert play_res.status_code == 200, (
            f"Playground chat failed: {play_res.status_code} {play_res.text}"
        )
        play_data = play_res.json()
        logger.info(
            "✓ Playground Chat Response: %s (Provider: %s, Latency: %dms, Tokens: %d)",
            play_data["reply"].strip(),
            play_data["provider"],
            play_data["latency_ms"],
            play_data["tokens"]["total_tokens"],
        )

        # 9. Compare Arena
        logger.info("\n=== 9. Testing Compare Arena (/api/arena/compare) ===")
        compare_res = await client.post(
            "/api/arena/compare",
            headers=headers,
            json={
                "prompt": "Say hello in 3 words",
                "models": ["fast", "smart"],
                "judge": True,
                "judge_model": "fast",
            },
        )
        assert compare_res.status_code == 200, (
            f"Compare Arena failed: {compare_res.status_code} {compare_res.text}"
        )
        comp_data = compare_res.json()
        logger.info(
            "✓ Compare Arena Run Completed (ID: %s, Ranking: %s):",
            comp_data["run_id"],
            comp_data.get("ranking"),
        )
        for m in comp_data.get("models", []):
            logger.info(
                "   - Model: %s | Provider: %s | Latency: %dms | Output: %s",
                m["model"],
                m.get("provider"),
                m.get("latency_ms", 0),
                (m.get("output") or "").strip()[:80],
            )

        # 10. Debate Arena
        logger.info("\n=== 10. Testing Debate Arena (/api/arena/debate) ===")
        debate_res = await client.post(
            "/api/arena/debate",
            headers=headers,
            json={
                "topic": "Tabs vs Spaces for indentation",
                "model_a": "fast",
                "model_b": "smart",
                "judge_model": "fast",
                "rounds": 1,
            },
        )
        assert debate_res.status_code == 200, (
            f"Debate Arena failed: {debate_res.status_code} {debate_res.text}"
        )
        debate_data = debate_res.json()
        logger.info(
            "✓ Debate Arena Completed (ID: %s, Verdict: %s):",
            debate_data["run_id"],
            debate_data.get("verdict"),
        )
        for turn in debate_data.get("turns", []):
            logger.info(
                "   - Round %d (%s as %s): %s",
                turn["round"],
                turn["model"],
                turn["side"],
                turn["content"][:80] + "...",
            )

        logger.info("\n=======================================================")
        logger.info("🎉 ALL 10 E2E LIVE INTEGRATION TESTS PASSED WITH 100% SUCCESS!")
        logger.info("=======================================================")


if __name__ == "__main__":
    asyncio.run(run_e2e())
