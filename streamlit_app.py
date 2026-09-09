from __future__ import annotations

import asyncio
import hmac
import json
import re
import uuid
from collections.abc import Coroutine
from typing import Any
from urllib.parse import urlparse

import httpx
import pandas as pd
import streamlit as st

from codeflux.config import Settings, load_config
from codeflux.storage import CredentialVault, Database, UsageRepository, WorkflowRepository

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
            return await UsageRepository(database.sessions).summary()
        if action == "credentials":
            return await CredentialVault(database.sessions, settings.master_secret).list_metadata()
        if action == "put_credential":
            return await CredentialVault(database.sessions, settings.master_secret).put(*args)
        workflows = WorkflowRepository(database.sessions)
        return await getattr(workflows, action)(*args)
    finally:
        await database.close()


def gateway_get(path: str) -> dict[str, Any]:
    response = httpx.get(
        f"{gateway_base_url()}{path}",
        headers={"Authorization": f"Bearer {st.session_state.gateway_key}"},
        timeout=5,
    )
    response.raise_for_status()
    return response.json()


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
    st.session_state.gateway_key = next(iter(settings.client_keys()), "demo-key")
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

st.title("CodeFlux control room", icon=":material/hub:")
st.caption("Plan work once, retain progress across provider changes, and combine trusted API-key quotas.")

overview_tab, workflow_tab, pool_tab = st.tabs(
    [":material/monitoring: Overview", ":material/checklist: Work planner", ":material/key: Quota pool"]
)

with overview_tab:
    usage = run_async(with_storage("usage"))
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
        known = sum(1 for item in live.get("limits", []) if item.get("remaining_requests") is not None)
        st.metric("Keys with known request limit", known, border=True)
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
            height=160,
            placeholder="Describe the complete outcome, constraints, audience, and definition of done.",
        )
        generate = st.form_submit_button("Generate checklist", type="primary", icon=":material/auto_awesome:")
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
        selected_id = st.selectbox(
            "Open project", list(workflow_by_id), index=list(workflow_by_id).index(default_id) if default_id in workflow_by_id else 0,
            format_func=lambda value: workflow_by_id[value]["title"],
        )
        workflow = workflow_by_id[selected_id]
        completed = sum(item["completed"] for item in workflow["items"])
        total = len(workflow["items"])
        st.progress(completed / total if total else 0, text=f"{completed} of {total} tasks completed")
        with st.expander("Master prompt", icon=":material/description:"):
            st.write(workflow["master_prompt"])
        for item in workflow["items"]:
            checked = st.checkbox(item["text"], value=item["completed"], key=f"item_{item['id']}")
            if checked != item["completed"]:
                run_async(with_storage("set_item", item["id"], checked))
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
        if not contributor.strip() or not api_key.strip():
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
