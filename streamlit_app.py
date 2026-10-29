from __future__ import annotations

import asyncio
import hmac
import importlib
import re
import uuid
from collections.abc import Coroutine
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import pandas as pd
import streamlit as st

import codeflux.storage

importlib.reload(codeflux.storage)

from codeflux.config import Settings, load_config
from codeflux.planner import PLANNER_PROMPT, checklist_from_response
from codeflux.runner import StepResult, WorkflowRunner
from codeflux.storage import (
    ClientKeyRepository,
    CredentialVault,
    Database,
    UsageRepository,
    WorkflowRepository,
)

PROJECT_ROOT = Path(__file__).resolve().parent

st.set_page_config(page_title="CodeFlux — AI task control room", page_icon=":material/hub:", layout="wide")


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
        if action == "authenticate_client_key":
            return await client_keys.authenticate(*args)
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


def public_base_url() -> str:
    """The address apps should use; inside Docker the dashboard's own URL is internal."""
    return (settings.public_url or gateway_base_url()).rstrip("/")


def current_identity() -> dict[str, Any]:
    try:
        return gateway_get("/v1/me")
    except (httpx.HTTPError, ValueError):
        # Gateway offline: fall back to what was verified at sign-in.
        return st.session_state.login_identity


def sign_in(role: str, key: str | None, identity: dict[str, Any]) -> None:
    st.session_state.role = role
    st.session_state.gateway_key = key or ""
    st.session_state.login_identity = identity
    st.rerun()


def sign_out() -> None:
    for name in ("role", "gateway_key", "login_identity"):
        st.session_state.pop(name, None)


def teammate_identity(key: str) -> dict[str, Any] | None:
    for bootstrap_key, team in settings.client_keys().items():
        if hmac.compare_digest(key, bootstrap_key):
            return {"team": team, "name": team, "monthly_token_limit": None}
    return run_async(with_storage("authenticate_client_key", key))


def ask_gateway(model: str, messages: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
    response = httpx.post(
        f"{gateway_base_url()}/v1/chat/completions",
        headers={"Authorization": f"Bearer {st.session_state.gateway_key}"},
        json={"model": model, "messages": messages},
        timeout=190,
    )
    if response.is_error:
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = response.text[:300]
        if "no-key" in message:
            message += (
                " — no usable provider key. Add one in **Quota pool**; keys marked unusable "
                "there were saved with a different CODEFLUX_MASTER_SECRET."
            )
        raise ValueError(f"gateway returned {response.status_code}: {message}")
    body = response.json()
    return body["choices"][0]["message"]["content"], body.get("codeflux", {})


def done_by(result: str | None, task: str) -> str | None:
    """Describe who did a task and whether its checks passed, from the runner's saved section."""
    match = re.search(
        rf"^## {re.escape(task)}\s*\n+_Model: `([^`]+)` via `([^`]+)`_(.*?)(?=^## |\Z)",
        result or "", re.MULTILINE | re.DOTALL,
    )
    if not match:
        return None
    who = f"`{match[1]}` via `{match[2]}`"
    if "**Checks failed**" in match[3]:
        return f":orange[:material/warning: Done, but checks failed] · {who}"
    if "Checks: passed" in match[3]:
        return f":green[:material/verified: Done, checks passed] · {who}"
    return f":green[:material/check_circle: Done] · {who}"


def chat_route_names() -> list[str]:
    """Return routes that can handle planner chat requests."""
    return [
        alias
        for alias, route in config.routes.items()
        if route.candidates
        and all(not candidate.model.startswith("text-embedding") for candidate in route.candidates)
    ]


def route_label(alias: str) -> str:
    route = config.routes[alias]
    primary = route.candidates[0]
    fallback_count = len(route.candidates) - 1 + int(bool(route.ollama_fallback_model))
    groq_fallback = any(candidate.provider == "groq" for candidate in route.candidates[1:])
    if groq_fallback:
        extra_count = fallback_count - 1
        fallback_text = " · Groq fallback"
        if extra_count:
            fallback_text += f" + {extra_count} more"
    else:
        fallback_text = f" · {fallback_count} fallback{'s' if fallback_count != 1 else ''}" if fallback_count else ""
    return f"{primary.model} ({primary.provider}){fallback_text}"


settings = Settings()
config = load_config(settings.config_path)
ADMIN_IDENTITY = {"team": "admin", "name": "admin", "monthly_token_limit": None}
st.session_state.setdefault("gateway_url", settings.dashboard_gateway_url)
st.session_state.setdefault("active_route", next(iter(config.routes), ""))
planner_routes = chat_route_names()
if not planner_routes:
    st.error("No chat-capable AI routes are configured for the work planner.")
    st.stop()
if st.session_state.active_route not in planner_routes:
    st.session_state.active_route = planner_routes[0]

if not settings.dashboard_password and "role" not in st.session_state:
    # No password configured: single-user local mode, signed in as admin.
    st.session_state.role = "admin"
    st.session_state.gateway_key = settings.admin_key() or ""
    st.session_state.login_identity = ADMIN_IDENTITY

if "role" not in st.session_state:
    st.title("Sign in to CodeFlux", icon=":material/hub:")
    admin_tab, teammate_tab = st.tabs([":material/shield_person: Admin", ":material/person: Teammate"])
    with admin_tab, st.form("admin_login"):
        supplied_password = st.text_input("Dashboard password", type="password")
        admin_login = st.form_submit_button("Sign in", type="primary", icon=":material/login:")
    if admin_login:
        if hmac.compare_digest(supplied_password, settings.dashboard_password):
            sign_in("admin", settings.admin_key(), ADMIN_IDENTITY)
        st.error("Incorrect dashboard password.")
    with teammate_tab, st.form("teammate_login"):
        supplied_key = st.text_input("Your CodeFlux API key", type="password", placeholder="cf_...")
        st.caption("Ask your admin for a key. It is the same key you use in your projects.")
        teammate_login = st.form_submit_button("Sign in", type="primary", icon=":material/login:")
    if teammate_login:
        verified = teammate_identity(supplied_key.strip()) if supplied_key.strip() else None
        if verified:
            sign_in("admin" if verified["team"] == "admin" else "member", supplied_key.strip(), verified)
        st.error("That CodeFlux API key is not valid or has been revoked.")
    st.stop()

is_admin = st.session_state.role == "admin"
identity = current_identity()
with st.sidebar:
    st.success(f"Signed in as **{identity.get('name') or identity['team']}** · team {identity['team']}", icon=":material/verified_user:")
    if settings.dashboard_password:
        st.button("Sign out", icon=":material/logout:", on_click=sign_out)
    else:
        st.caption("Local mode: set `CODEFLUX_DASHBOARD_PASSWORD` to require sign-in.")
    if is_admin and not st.session_state.gateway_key:
        st.warning("Add an admin key to `CODEFLUX_GATEWAY_KEYS` (for example `my-secret:admin`) so the dashboard can call the gateway.", icon=":material/key_off:")
    with st.expander("Gateway address", icon=":material/link:"):
        st.text_input("Gateway URL", key="gateway_url", help="Only change this if the gateway is not on this machine.")
        st.button(
            "Reset", icon=":material/restart_alt:",
            on_click=lambda: st.session_state.update(gateway_url=settings.dashboard_gateway_url),
        )

with st.container(border=True):
    st.title("CodeFlux", icon=":material/hub:")
    st.markdown("### One place to plan, route, and complete work with the right AI model.")
    st.write(
        "Turn a master prompt into an actionable checklist, keep progress safely persisted, "
        "and let CodeFlux route each task across your trusted model providers."
    )
    with st.container(horizontal=True):
        st.badge("Smart model routing", icon=":material/route:", color="blue")
        st.badge("Persistent task plans", icon=":material/checklist:", color="violet")
        st.badge("Shared quota pool", icon=":material/key:", color="green")

overview_tab, workflow_tab, pool_tab, access_tab = st.tabs(
    [":material/monitoring: Overview", ":material/checklist: Task planner", ":material/key: Quota pool", ":material/api: API access"]
)

with overview_tab:
    usage = run_async(with_storage("usage", None if is_admin else identity["team"]))
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
    if "tokens_used_this_month" in identity:
        used_this_month = int(identity["tokens_used_this_month"])
        left_this_month = identity.get("tokens_left_this_month")
        budget_text = "unlimited" if left_this_month is None else f"{int(left_this_month):,} left"
        st.caption(f"Your team has used **{used_this_month:,} tokens** this calendar month · **{budget_text}** on this key's budget.")
    if usage.get("by_team") and is_admin:
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
    st.subheader("Turn an idea into an actionable plan", icon=":material/edit_note:")
    st.caption("Describe the outcome once, choose your model, and CodeFlux will create a reusable task list.")
    with st.container(border=True), st.form("new_workflow", border=False):
        title = st.text_input("Project title", placeholder="Professor demo")
        master_prompt = st.text_area(
            "Master prompt",
            height=130,
            placeholder="Describe the complete outcome, constraints, audience, and definition of done.",
        )
        generation_route = st.selectbox(
            "Model for checklist",
            planner_routes,
            index=planner_routes.index(st.session_state.active_route),
            format_func=route_label,
            help="CodeFlux uses the selected model first, then its configured fallbacks if needed.",
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
            workflow_id = run_async(
                with_storage(
                    "create", title.strip(), master_prompt.strip() or "Manual project", [], st.session_state.active_route
                )
            )
            st.session_state.selected_workflow = workflow_id
            st.rerun()
    if generate:
        if not title.strip() or not master_prompt.strip():
            st.error("Add both a title and a master prompt.")
        else:
            try:
                with st.status("Asking the AI to structure the work…", expanded=True) as status:
                    response, route_info = ask_gateway(generation_route, [
                        {"role": "system", "content": PLANNER_PROMPT},
                        {"role": "user", "content": master_prompt},
                    ])
                    workflow_id = run_async(
                        with_storage(
                            "create", title.strip(), master_prompt.strip(), checklist_from_response(response), generation_route
                        )
                    )
                    status.update(label="Checklist created", state="complete", expanded=False)
                st.session_state.selected_workflow = workflow_id
                st.session_state.last_route_info = route_info
                st.rerun()
            except (httpx.HTTPError, ValueError) as exc:
                if isinstance(exc, httpx.ConnectError):
                    st.error(
                        f"Could not reach the gateway at `{st.session_state.gateway_url}` ({exc}). "
                        "Check that `python -m codeflux` is running, or use **Reset** under "
                        "**Gateway address** in the sidebar."
                    )
                else:
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
        with st.container(horizontal=True, vertical_alignment="center"):
            if total and completed == total:
                st.badge("All tasks done", icon=":material/task_alt:", color="green")
            elif completed:
                st.badge(f"In progress · {total - completed} left", icon=":material/pending:", color="orange")
            else:
                st.badge("Not started", icon=":material/radio_button_unchecked:", color="gray")
        st.progress(completed / total if total else 0, text=f"{completed} of {total} tasks completed")
        with st.expander("Master prompt", icon=":material/description:"):
            st.write(workflow["master_prompt"])

        if workflow["items"]:
            with st.container(horizontal=True):
                if st.button("Check all", icon=":material/done_all:", key=f"check_all_{selected_id}"):
                    for item in workflow["items"]:
                        if not item["completed"]:
                            run_async(with_storage("set_item", item["id"], True))
                    st.rerun()
                if st.button("Uncheck all", icon=":material/remove_done:", key=f"uncheck_all_{selected_id}"):
                    for item in workflow["items"]:
                        if item["completed"]:
                            run_async(with_storage("set_item", item["id"], False))
                    st.rerun()

        for item in workflow["items"]:
            # The database is the source of truth: the runner and other teammates change it too,
            # so the widget is reset from it on every run and only a real click writes back.
            st.session_state[f"item_{item['id']}"] = item["completed"]
            col_check, col_model, col_del_item = st.columns([6, 3, 1], vertical_alignment="bottom")
            with col_check:
                label = f":green[~~{item['text']}~~]" if item["completed"] else item["text"]
                st.checkbox(
                    label, key=f"item_{item['id']}",
                    on_change=lambda item_id=item["id"]: run_async(
                        with_storage("set_item", item_id, st.session_state[f"item_{item_id}"])
                    ),
                )
                if item["completed"] and (status := done_by(workflow.get("result"), item["text"])):
                    st.caption(status)
            with col_model:
                saved_route = item.get("model_route")
                if saved_route not in planner_routes:
                    saved_route = planner_routes[0]
                assigned_route = st.selectbox(
                    f"Model for {item['text']}",
                    planner_routes,
                    index=planner_routes.index(saved_route),
                    format_func=route_label,
                    label_visibility="collapsed",
                    help=f"Choose the model that will handle: {item['text']}",
                    key=f"item_model_{item['id']}",
                )
                if assigned_route != item.get("model_route"):
                    run_async(with_storage("set_item_model", item["id"], assigned_route))
            with col_del_item:
                if st.button("✕", key=f"del_item_{item['id']}", help="Delete item"):
                    run_async(with_storage("delete_item", item["id"]))
                    st.rerun()

        with st.form(f"add_item_{selected_id}"):
            new_item = st.text_input("Add another checklist item")
            new_item_route = st.selectbox("Model for new item", planner_routes, format_func=route_label)
            add = st.form_submit_button("Add item", icon=":material/add:")
        if add and new_item.strip():
            run_async(with_storage("add_item", selected_id, new_item.strip(), new_item_route))
            st.rerun()
        with st.container(border=True):
            st.subheader("Do the work with CodeFlux", icon=":material/smart_toy:")
            st.write(
                "CodeFlux works through the unchecked tasks in order through its own API. Each task "
                "uses the model chosen next to it and receives the master prompt, the full plan, "
                "every earlier task's result, and the current files in the workspace folder. After "
                "each task CodeFlux compiles the code, runs the tests, and loads any Streamlit app; "
                "failures go back to the model to fix before the task is ticked."
            )
            slug = re.sub(r"[^a-z0-9]+", "-", workflow["title"].lower()).strip("-") or f"project-{selected_id}"
            workspace_name = st.text_input(
                "Workspace folder", value=f"demo/{slug}", key=f"workspace_{selected_id}",
                help="Relative to the CodeFlux folder. Models can only write files inside it.",
            )
            with st.container(horizontal=True):
                run_one = st.button("Run next task", icon=":material/play_arrow:", key=f"run_one_{selected_id}")
                run_all = st.button(
                    "Run all remaining tasks", type="primary", icon=":material/fast_forward:",
                    key=f"run_all_{selected_id}",
                )
            if run_one or run_all:
                workspace = (PROJECT_ROOT / workspace_name.strip()).resolve()
                if not workspace_name.strip() or not workspace.is_relative_to(PROJECT_ROOT) or workspace == PROJECT_ROOT:
                    st.error("Choose a sub-folder inside the CodeFlux folder, such as `demo/my-project`.")
                else:
                    runner = WorkflowRunner(gateway_base_url(), st.session_state.gateway_key, workspace)
                    log: list[str] = []
                    with st.status("Starting…", expanded=True) as run_status:
                        def started(task: str, model: str) -> None:
                            run_status.update(label=f"Working on: {task}")
                            st.write(f":material/pending: **{task}** with `{model}`…")

                        def finished(step: StepResult) -> None:
                            files = ", ".join(f"`{name}`" for name in step.files) or "no files"
                            fixes = f" after {step.fix_attempts} fix attempt(s)" if step.fix_attempts else ""
                            if step.problems:
                                icon, checks = ":orange[:material/warning:]", f"checks **failed**{fixes}: {step.problems[0].splitlines()[0]}"
                            elif step.files:
                                icon, checks = ":green[:material/verified:]", f"checks passed{fixes}"
                            else:
                                icon, checks = ":orange[:material/warning:]", "nothing was written"
                            line = f"{icon} **{step.task}**: answered by `{step.provider}`, wrote {files}; {checks}"
                            log.append(line)
                            st.write(line)

                        def repaired(round_number: int, files: list[str], problems: list[str]) -> None:
                            run_status.update(label=f"Repairing the whole project (round {round_number})")
                            wrote = ", ".join(f"`{name}`" for name in files) or "nothing"
                            if problems:
                                line = f":orange[:material/build:] Repair {round_number}: wrote {wrote}; still failing: {problems[0].splitlines()[0]}"
                            else:
                                line = f":green[:material/build:] Repair {round_number}: wrote {wrote}; the project now passes every check"
                            log.append(line)
                            st.write(line)

                        def accepted(files: list[str]) -> None:
                            if files:
                                line = ":blue[:material/fact_check:] Wrote `test_acceptance.py`: it uses the app like a person would to check every requested feature"
                            else:
                                line = ":gray[:material/fact_check:] No new acceptance test written (one already exists, or the model returned none)"
                            log.append(line)
                            st.write(line)
                            run_status.update(label="Checking the finished app end to end")

                        try:
                            steps = runner.run(selected_id, None if run_all else 1, started, finished, repaired, accepted)
                        except (RuntimeError, httpx.HTTPError, ValueError) as exc:
                            steps = []
                            log.append(f":red[:material/error:] Stopped: {exc}")
                            run_status.update(label="Stopped with an error", state="error")
                            st.error(str(exc))
                        else:
                            if runner.final_problems is not None:
                                remaining = runner.final_problems
                                verdict = (
                                    ":red[:material/cancel:] **Final check failed**: the app does not fully work yet: "
                                    + "; ".join(problem.splitlines()[0] for problem in remaining[:3])
                                    if remaining else
                                    ":green[:material/verified:] **Final check passed**: the app compiles, its tests "
                                    "pass, it loads, and a review found every requested feature."
                                )
                                log.append(verdict)
                                st.markdown(verdict)
                            run_status.update(
                                label=f"Finished {len(steps)} task(s)" if steps else "Nothing left to do",
                                state="complete",
                            )
                    st.session_state[f"run_log_{selected_id}"] = log
                    if log:
                        st.rerun()  # redraw the checklist with the newly ticked tasks
            if log_lines := st.session_state.get(f"run_log_{selected_id}"):
                with st.expander("Last run", icon=":material/history:", expanded=True):
                    for line in log_lines:
                        st.markdown(line)
                    st.caption(f"Files are in `{(PROJECT_ROOT / workspace_name.strip()).resolve()}`")
        with st.expander("Use your own IDE agent instead", icon=":material/code:"):
            st.write(
                "Your IDE agent can fetch the next incomplete task with its assigned model and shared "
                "project context, perform the work locally, then report the result to CodeFlux."
            )
            st.code(
                f"GET {public_base_url()}/v1/ide/workflows/{selected_id}/next-task\n"
                "Authorization: Bearer <your cf_... key>",
                language="http",
            )
            st.caption(
                "The response includes `model` and `messages` for the next task. After your IDE finishes, "
                "POST its summary to the completion URL returned in the integration guide."
            )
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
        counts = rows.groupby("provider").agg(**{"encrypted keys": ("usable", "size"), "usable keys": ("usable", "sum")}).reset_index()
        st.dataframe(counts, hide_index=True)
        unusable = [item["reference"] for item in credentials if not item["usable"]]
        if unusable:
            st.warning(
                f"{len(unusable)} key(s) cannot be decrypted with the current `CODEFLUX_MASTER_SECRET` "
                "and are skipped: " + ", ".join(f"`{ref}`" for ref in unusable)
                + ". Restore the old secret or add the keys again.",
                icon=":material/key_off:",
            )
        with st.expander("Credential references", icon=":material/visibility:"):
            st.dataframe(rows, hide_index=True)
    else:
        st.info("The encrypted key pool is empty.")

with access_tab:
    st.subheader("Use CodeFlux in your project", icon=":material/rocket_launch:")
    st.write(
        "CodeFlux speaks the OpenAI API, so any project or tool that works with OpenAI works with "
        "CodeFlux: point it at the base URL below and use your CodeFlux key as the API key."
    )
    base_url = public_base_url()
    your_key = st.session_state.gateway_key
    with st.container(border=True):
        st.markdown("**Base URL**")
        st.code(f"{base_url}/v1", language=None)
        st.markdown("**Your API key**")
        if not your_key:
            st.info("No admin key is configured. Create a teammate key below and use that one.", icon=":material/info:")
        elif st.toggle("Show my key", key="show_key"):
            st.code(your_key, language=None)
        else:
            st.code(f"{your_key[:6]}{'•' * 20}", language=None)
        st.markdown("**Models**")
        st.caption(
            "Use a CodeFlux route below, or any provider model name such as `gpt-4o-mini` or "
            "`gemini-2.0-flash`. Unknown names go to the default route with automatic failover."
        )
        st.markdown(" ".join(f"`{alias}`" for alias in config.routes))

    key_hint = "your-codeflux-key"
    model = planner_routes[0]
    env_tab, python_tab, js_tab, curl_tab, gemini_tab = st.tabs(
        ["Environment variables", "Python", "JavaScript", "curl", "Gemini SDK"]
    )
    with env_tab:
        st.caption("Most OpenAI-based apps and tools read these, so they need no code changes.")
        st.code(f"OPENAI_BASE_URL={base_url}/v1\nOPENAI_API_KEY={key_hint}", language="bash")
    with python_tab:
        st.caption("`pip install openai`")
        st.code(
            "from openai import OpenAI\n\n"
            f'client = OpenAI(base_url="{base_url}/v1", api_key="{key_hint}")\n'
            "response = client.chat.completions.create(\n"
            f'    model="{model}",\n'
            '    messages=[{"role": "user", "content": "Hello!"}],\n'
            ")\n"
            "print(response.choices[0].message.content)",
            language="python",
        )
    with js_tab:
        st.caption("`npm install openai`")
        st.code(
            'import OpenAI from "openai";\n\n'
            f'const client = new OpenAI({{ baseURL: "{base_url}/v1", apiKey: "{key_hint}" }});\n'
            "const response = await client.chat.completions.create({\n"
            f'  model: "{model}",\n'
            '  messages: [{ role: "user", content: "Hello!" }],\n'
            "});\n"
            "console.log(response.choices[0].message.content);",
            language="javascript",
        )
    with curl_tab:
        st.code(
            f"curl {base_url}/v1/chat/completions \\n"
            f'  -H "Authorization: Bearer {key_hint}" \\n'
            '  -H "Content-Type: application/json" \\n'
            f'  -d \'{{"model": "{model}", "messages": [{{"role": "user", "content": "Hello!"}}]}}\'',
            language="bash",
        )
    with gemini_tab:
        st.caption("`pip install google-genai`")
        st.code(
            "from google import genai\n\n"
            f'client = genai.Client(api_key="{key_hint}", http_options={{"base_url": "{base_url}"}})\n'
            f'response = client.models.generate_content(model="{model}", contents="Hello!")\n'
            "print(response.text)",
            language="python",
        )

    if not is_admin:
        team_usage = run_async(with_storage("usage", identity["team"]))
        st.subheader("Your usage", icon=":material/speed:")
        with st.container(horizontal=True):
            st.metric("Team", identity["team"], border=True)
            st.metric("Requests", team_usage["requests"], border=True)
            st.metric("Tokens used", team_usage["total_tokens"], border=True)
            remaining = identity.get("tokens_left_this_month")
            st.metric("Tokens left this month", "Unlimited" if remaining is None else f"{int(remaining):,}", border=True)
    else:
        st.subheader("Teammate keys", icon=":material/group_add:")
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
            active_keys = {item["id"]: item for item in managed_keys if item["active"]}
            if active_keys:
                with st.container(horizontal=True, vertical_alignment="bottom"):
                    revoke_id = st.selectbox(
                        "Revoke a key", list(active_keys),
                        format_func=lambda value: f"{active_keys[value]['name']} ({active_keys[value]['team']}) · {active_keys[value]['key_prefix']}",
                    )
                    if st.button("Revoke", icon=":material/block:"):
                        run_async(with_storage("revoke_client_key", revoke_id))
                        st.rerun()
