from __future__ import annotations

import asyncio
import hmac
import importlib
import json
import re
import uuid
from collections.abc import Coroutine
from typing import Any
from urllib.parse import urlparse

import httpx
import pandas as pd
import streamlit as st

import codeflux.storage

importlib.reload(codeflux.storage)

from codeflux.config import Settings, load_config
from codeflux.storage import (
    ClientKeyRepository,
    CredentialVault,
    Database,
    UsageRepository,
    WorkflowRepository,
)

st.set_page_config(page_title="CodeFlux control room", page_icon=":material/hub:", layout="wide")


def run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


def gateway_base_url() -> str:
    value = st.session_state.gateway_url.strip()
    if not value:
        raise ValueError("Gateway URL is empty. Use http://localhost:8000")
    if "://" not in value:
        value = f"http://{value}"
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Gateway URL must look like http://localhost:8000")
    return value.rstrip("/")


async def with_storage(action: str, *args: Any) -> Any:
    settings = Settings()
    database = Database(settings.database_url)
    await database.initialize()
    try:
        if action == "usage":
            return await UsageRepository(database.sessions).summary(*args)
        if action == "credentials":
            return await CredentialVault(database.sessions, settings.master_secret).list_metadata()
        if action == "put_credential":
            return await CredentialVault(database.sessions, settings.master_secret).put(*args)
        client_keys = ClientKeyRepository(database.sessions, settings.master_secret)
        if action == "client_keys":
            return await client_keys.list()
        if action == "create_client_key":
            return await client_keys.create(*args)
        if action == "revoke_client_key":
            return await client_keys.revoke(*args)
        workflows = WorkflowRepository(database.sessions)
        return await getattr(workflows, action)(*args)
    finally:
        await database.close()


def gateway_get(path: str) -> dict[str, Any]:
    response = httpx.get(
        f"{gateway_base_url()}{path}",
        headers={"Authorization": f"Bearer {st.session_state.gateway_key}"},
        timeout=2,
    )
    response.raise_for_status()
    return response.json()


def current_identity() -> dict[str, Any] | None:
    try:
        return gateway_get("/v1/me")
    except (httpx.HTTPError, ValueError):
        return None


def ask_gateway(model: str, messages: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
    response = httpx.post(
        f"{gateway_base_url()}/v1/chat/completions",
        headers={"Authorization": f"Bearer {st.session_state.gateway_key}"},
        json={"model": model, "messages": messages},
        timeout=190,
    )
    response.raise_for_status()
    body = response.json()
    return body["choices"][0]["message"]["content"], body.get("codeflux", {})


def checklist_from_response(text: str) -> list[str]:
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            values = json.loads(match.group(0))
            if isinstance(values, list):
                items = [str(item).strip() for item in values if str(item).strip()]
                if items:
                    return items
        except json.JSONDecodeError:
            pass
    return [
        re.sub(r"^\s*(?:[-*]|\d+[.)]|\[[ xX]\])\s*", "", line).strip()
        for line in text.splitlines()
        if re.match(r"^\s*(?:[-*]|\d+[.)]|\[[ xX]\])\s+", line)
    ] or ["Review and refine the plan before execution"]


settings = Settings()
config = load_config(settings.config_path)
if "gateway_url" not in st.session_state:
    # Streamlit can retain an older imported Settings class across a hot reload.
    st.session_state.gateway_url = getattr(
        settings, "dashboard_gateway_url", f"http://localhost:{settings.port}"
    )
if "gateway_key" not in st.session_state:
    st.session_state.gateway_key = ""
if "active_route" not in st.session_state:
    st.session_state.active_route = next(iter(config.routes), "")

if settings.dashboard_password and not st.session_state.get("dashboard_authenticated"):
    st.title("CodeFlux control room", icon=":material/lock:")
    with st.form("dashboard_login"):
        supplied_password = st.text_input("Dashboard password", type="password")
        login = st.form_submit_button("Sign in", type="primary")
    if login and hmac.compare_digest(supplied_password, settings.dashboard_password):
        st.session_state.dashboard_authenticated = True
        st.rerun()
    if login:
        st.error("Incorrect dashboard password.")
    st.stop()

with st.sidebar:
    st.header("Connection", icon=":material/link:")
    st.text_input("Gateway URL", key="gateway_url")
    st.text_input("Gateway API key", key="gateway_key", type="password")
    st.selectbox("AI route", list(config.routes), key="active_route")
    st.caption("The dashboard is an administrator interface. Do not expose it publicly without authentication and TLS.")

identity = current_identity() if st.session_state.gateway_key else None
if st.session_state.gateway_key and identity is None:
    st.warning("That CodeFlux API key could not be verified. Check the key and gateway URL.", icon=":material/key_off:")
if identity:
    with st.sidebar:
        st.success(f"Signed in to team: {identity['team']}", icon=":material/verified_user:")

st.title("CodeFlux control room", icon=":material/hub:")
st.caption("Plan work once, retain progress across provider changes, and combine trusted API-key quotas.")

overview_tab, workflow_tab, pool_tab, access_tab = st.tabs(
    [":material/monitoring: Overview", ":material/checklist: Work planner", ":material/key: Quota pool", ":material/group: Team access"]
)

with overview_tab:
    usage = run_async(with_storage("usage", None if identity and identity["team"] == "admin" else (identity or {}).get("team")))
    try:
        live = gateway_get("/dashboard/status")
        online = True
    except (httpx.HTTPError, ValueError):
        live, online = {"last_route": None, "limits": [], "circuits": {}}, False
    latest = live.get("last_route") or usage.get("latest") or {}
    with st.container(horizontal=True):
        st.metric("Gateway", "Online" if online else "Offline", border=True)
        st.metric("Current provider", latest.get("provider", "No calls yet"), border=True)
        st.metric("Current model", latest.get("model", "No calls yet"), border=True)
        st.metric("Recorded requests", usage["requests"], border=True)
    st.subheader("Usage and limits", icon=":material/speed:")
    st.caption("Exact account quota is provider-owned. CodeFlux shows request/token use and any rate-limit values learned from provider headers; ‘Unknown’ is not unlimited.")
    with st.container(horizontal=True):
        st.metric("Prompt tokens", usage["prompt_tokens"], border=True)
        st.metric("Completion tokens", usage["completion_tokens"], border=True)
        st.metric("Total tokens used", usage["total_tokens"], border=True)
        known = sum(1 for item in live.get("limits", []) if item.get("remaining_requests") is not None)
        st.metric("Keys with known request limit", known, border=True)
    if identity:
        used_this_month = int(identity.get("tokens_used_this_month", 0))
        left_this_month = identity.get("tokens_left_this_month")
        budget_text = "unlimited" if left_this_month is None else f"{int(left_this_month):,} left"
        st.caption(f"Your team has used **{used_this_month:,} tokens** this calendar month · **{budget_text}** on this key's budget.")
    if usage.get("by_team") and identity and identity["team"] == "admin":
        st.subheader("Usage by team", icon=":material/groups:")
        st.dataframe(pd.DataFrame(usage["by_team"]), hide_index=True)
    limits = live.get("limits", [])
    if limits:
        st.dataframe(pd.DataFrame(limits).fillna("Unknown"), hide_index=True)
    else:
        st.info("No live provider limit headers have been observed yet.", icon=":material/info:")
    if live.get("circuits"):
        st.subheader("Circuit state", icon=":material/electrical_services:")
        st.json(live["circuits"])

with workflow_tab:
    st.subheader("Create a plan from a master prompt", icon=":material/edit_note:")
    with st.form("new_workflow"):
        title = st.text_input("Project title", placeholder="Professor demo")
        master_prompt = st.text_area(
            "Master prompt",
            height=130,
            placeholder="Describe the complete outcome, constraints, audience, and definition of done.",
        )
        col_gen, col_manual = st.columns([1, 1])
        with col_gen:
            generate = st.form_submit_button("Generate checklist with AI", type="primary", icon=":material/auto_awesome:")
        with col_manual:
            create_manual = st.form_submit_button("Create empty project", icon=":material/add:")
    if create_manual:
        if not title.strip():
            st.error("Add a title for your project.")
        else:
            workflow_id = run_async(with_storage("create", title.strip(), master_prompt.strip() or "Manual project", []))
            st.session_state.selected_workflow = workflow_id
            st.rerun()
    if generate:
        if not title.strip() or not master_prompt.strip():
            st.error("Add both a title and a master prompt.")
        else:
            try:
                with st.status("Asking the AI to structure the work…", expanded=True) as status:
                    response, route_info = ask_gateway(st.session_state.active_route, [
                        {"role": "system", "content": "Turn the user's project request into an actionable checklist. Return only a JSON array of concise checklist strings, ordered by dependency. Do not execute the work."},
                        {"role": "user", "content": master_prompt},
                    ])
                    workflow_id = run_async(with_storage("create", title.strip(), master_prompt.strip(), checklist_from_response(response)))
                    status.update(label="Checklist created", state="complete", expanded=False)
                st.session_state.selected_workflow = workflow_id
                st.session_state.last_route_info = route_info
                st.rerun()
            except (httpx.HTTPError, ValueError) as exc:
                st.error(f"The checklist could not be generated: {exc}")

    workflows = run_async(with_storage("list"))
    if not workflows:
        st.info("Create the first master prompt to begin tracking work.", icon=":material/lightbulb:")
    else:
        workflow_by_id = {item["id"]: item for item in workflows}
        default_id = st.session_state.get("selected_workflow", workflows[0]["id"])
        if default_id not in workflow_by_id:
            default_id = workflows[0]["id"]

        col_select, col_del = st.columns([4, 1])
        with col_select:
            selected_id = st.selectbox(
                "Open project", list(workflow_by_id), index=list(workflow_by_id).index(default_id),
                format_func=lambda value: workflow_by_id[value]["title"],
            )
        with col_del:
            st.write("")
            st.write("")
            if st.button("Delete project", type="secondary", icon=":material/delete:", key=f"del_proj_{selected_id}"):
                run_async(with_storage("delete", selected_id))
                st.session_state.pop("selected_workflow", None)
                st.rerun()

        workflow = workflow_by_id[selected_id]
        completed = sum(item["completed"] for item in workflow["items"])
        total = len(workflow["items"])
        st.progress(completed / total if total else 0, text=f"{completed} of {total} tasks completed")
        with st.expander("Master prompt", icon=":material/description:"):
            st.write(workflow["master_prompt"])

        if workflow["items"]:
            col_check_all, col_uncheck_all, _ = st.columns([1, 1, 3])
            with col_check_all:
                if st.button("Check all", icon=":material/done_all:", key=f"check_all_{selected_id}"):
                    for item in workflow["items"]:
                        if not item["completed"]:
                            run_async(with_storage("set_item", item["id"], True))
                            st.session_state[f"item_{item['id']}"] = True
                    st.rerun()
            with col_uncheck_all:
                if st.button("Uncheck all", icon=":material/remove_done:", key=f"uncheck_all_{selected_id}"):
                    for item in workflow["items"]:
                        if item["completed"]:
                            run_async(with_storage("set_item", item["id"], False))
                            st.session_state[f"item_{item['id']}"] = False
                    st.rerun()

        for item in workflow["items"]:
            col_check, col_del_item = st.columns([10, 1])
            with col_check:
                checked = st.checkbox(item["text"], value=item["completed"], key=f"item_{item['id']}")
                if checked != item["completed"]:
                    run_async(with_storage("set_item", item["id"], checked))
                    st.rerun()
            with col_del_item:
                if st.button("✕", key=f"del_item_{item['id']}", help="Delete item"):
                    run_async(with_storage("delete_item", item["id"]))
                    st.rerun()

        with st.form(f"add_item_{selected_id}"):
            new_item = st.text_input("Add another checklist item")
            add = st.form_submit_button("Add item", icon=":material/add:")
        if add and new_item.strip():
            run_async(with_storage("add_item", selected_id, new_item.strip()))
            st.rerun()
        if st.button("Do the work", type="primary", icon=":material/play_arrow:", key=f"execute_{selected_id}"):
            checklist = "\n".join(f"- [{'x' if item['completed'] else ' '}] {item['text']}" for item in workflow["items"])
            execution_prompt = f"MASTER REQUEST:\n{workflow['master_prompt']}\n\nPERSISTED CHECKLIST:\n{checklist}\n\nContinue the work using this progress record. Do not repeat completed items. Produce the requested deliverable and clearly state what was completed and what remains."
            try:
                with st.status("Executing from the persisted checklist…", expanded=True) as status:
                    result, route_info = ask_gateway(st.session_state.active_route, [{"role": "user", "content": execution_prompt}])
                    run_async(with_storage("save_result", selected_id, result))
                    status.update(label="AI response saved", state="complete", expanded=False)
                st.session_state.last_route_info = route_info
                st.rerun()
            except (httpx.HTTPError, ValueError) as exc:
                st.error(f"Execution failed, but the checklist is safely persisted: {exc}")
        if workflow.get("result"):
            st.subheader("Latest saved result", icon=":material/task_alt:")
            with st.chat_message("assistant"):
                st.markdown(workflow["result"])

with pool_tab:
    st.subheader("Contribute a provider key", icon=":material/vpn_key:")
    st.warning("Only add keys you are authorized to share. Keys are encrypted at rest, but all gateway users can consume the shared pool.", icon=":material/security:")
    providers = sorted({candidate.provider for route in config.routes.values() for candidate in route.candidates} | {"ollama"})
    with st.form("credential_form", clear_on_submit=True):
        contributor = st.text_input("Contributor name", placeholder="alice")
        provider = st.selectbox("Provider", providers)
        api_key = st.text_input("Provider API key", type="password")
        save_key = st.form_submit_button("Encrypt and add to pool", type="primary", icon=":material/add:")
    if save_key:
        if not identity:
            st.error("Enter a valid personal CodeFlux API key in the sidebar before contributing a provider key.")
        elif not contributor.strip() or not api_key.strip():
            st.error("Contributor name and API key are required.")
        else:
            reference = f"{provider}-{re.sub(r'[^a-z0-9-]', '-', contributor.lower()).strip('-')}-{uuid.uuid4().hex[:6]}"
            run_async(with_storage("put_credential", reference, provider, api_key.strip()))
            st.success(f"Added encrypted credential `{reference}` to the {provider} pool.")
    credentials = run_async(with_storage("credentials"))
    st.subheader("Available pool", icon=":material/group:")
    if credentials:
        rows = pd.DataFrame(credentials)
        counts = rows.groupby("provider").size().reset_index(name="encrypted keys")
        st.dataframe(counts, hide_index=True)
        with st.expander("Credential references", icon=":material/visibility:"):
            st.dataframe(rows, hide_index=True)
    else:
        st.info("The encrypted key pool is empty.")

with access_tab:
    st.subheader("CodeFlux API access", icon=":material/admin_panel_settings:")
    if not identity:
        st.info("Enter a valid Gateway API key in the sidebar to see your usage or manage team access.")
    elif identity["team"] != "admin":
        team_usage = run_async(with_storage("usage", identity["team"]))
        with st.container(horizontal=True):
            st.metric("Team", identity["team"], border=True)
            st.metric("Requests", team_usage["requests"], border=True)
            st.metric("Tokens used", team_usage["total_tokens"], border=True)
            remaining = identity.get("tokens_left_this_month")
            st.metric("Tokens left this month", "Unlimited" if remaining is None else f"{int(remaining):,}", border=True)
        st.code(f"CODEFLUX_BASE_URL={gateway_base_url()}/v1\nCODEFLUX_API_KEY=<your key>", language="dotenv")
    else:
        st.caption("Create a personal CodeFlux key for each teammate. The secret is shown once; CodeFlux stores only a one-way digest.")
        with st.form("create_client_key", clear_on_submit=True):
            member_name = st.text_input("Member name", placeholder="Alice")
            team_name = st.text_input("Team", placeholder="engineering")
            monthly_limit = st.number_input("Monthly token budget (0 = unlimited)", min_value=0, step=10_000)
            create_key = st.form_submit_button("Create CodeFlux key", type="primary", icon=":material/key:")
        if create_key:
            if not member_name.strip() or not team_name.strip():
                st.error("Member name and team are required.")
            else:
                secret = run_async(with_storage(
                    "create_client_key", member_name.strip(), team_name.strip(),
                    int(monthly_limit) or None,
                ))
                st.success("Key created. Copy it now; it cannot be displayed again.")
                st.code(secret, language=None)
        managed_keys = run_async(with_storage("client_keys"))
        if managed_keys:
            usage_by_team = {row["team"]: row["tokens_this_month"] for row in run_async(with_storage("usage"))["by_team"]}
            rows = []
            for item in managed_keys:
                used = int(usage_by_team.get(item["team"], 0))
                limit = item["monthly_token_limit"]
                rows.append({**item, "tokens_used_this_month": used, "tokens_left_this_month": None if limit is None else max(0, int(limit) - used)})
            st.dataframe(pd.DataFrame(rows), hide_index=True)
