import asyncio
from pathlib import Path

from streamlit.testing.v1 import AppTest

from codeflux.storage import Database, WorkflowRepository


async def seed_workflow(database_url: str) -> None:
    database = Database(database_url)
    await database.initialize()
    await WorkflowRepository(database.sessions).create(
        "IDE project", "Update the application", ["Implement the feature"], "gpt-4-tier"
    )
    await database.close()


def test_dashboard_renders(tmp_path, monkeypatch):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'dashboard.db'}"
    monkeypatch.setenv("CODEFLUX_DATABASE_URL", database_url)
    monkeypatch.setenv("CODEFLUX_DASHBOARD_PASSWORD", "")
    asyncio.run(seed_workflow(database_url))
    app = AppTest.from_file(Path(__file__).parents[1] / "streamlit_app.py", default_timeout=20).run()
    assert not app.exception
    assert app.title[0].value == "CodeFlux"
    labels = [tab.label for tab in app.tabs]
    assert all(any(name in label for label in labels) for name in ("Overview", "Task planner", "Quota pool", "API access"))
    assert any(selectbox.label == "Model for checklist" for selectbox in app.selectbox)
    assert any("One place to plan, route, and complete work" in markdown.value for markdown in app.markdown)
    assert any(subheader.value == "Do the work with CodeFlux" for subheader in app.subheader)
    assert any(button.label == "Run all remaining tasks" for button in app.button)
    assert not any(button.label == "Do the work" for button in app.button)
    assert any(subheader.value == "Teammate keys" for subheader in app.subheader)


def test_finished_tasks_show_as_done_and_follow_the_database(tmp_path, monkeypatch):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'dashboard.db'}"
    monkeypatch.setenv("CODEFLUX_DATABASE_URL", database_url)
    monkeypatch.setenv("CODEFLUX_DASHBOARD_PASSWORD", "")

    async def seed() -> tuple[int, int]:
        database = Database(database_url)
        await database.initialize()
        repository = WorkflowRepository(database.sessions)
        workflow_id = await repository.create("Demo", "Build it", ["Write code", "Write tests"], "gpt-4-tier")
        items = (await repository.list())[0]["items"]
        await repository.complete_ide_task(
            workflow_id, items[0]["id"], "_Model: `gpt-4-tier` via `groq`_\n\nDone.\n\nChecks: passed."
        )
        await database.close()
        return workflow_id, items[1]["id"]

    workflow_id, second_id = asyncio.run(seed())
    app = AppTest.from_file(Path(__file__).parents[1] / "streamlit_app.py", default_timeout=20).run()
    done, todo = app.checkbox[0], app.checkbox[1]
    assert done.value is True and done.label == ":green[~~Write code~~]"
    assert todo.value is False
    assert any("checks passed" in caption.value and "groq" in caption.value for caption in app.caption)

    # A task ticked elsewhere (by the runner) shows up on the next rerun instead of being undone.
    async def tick() -> None:
        database = Database(database_url)
        await database.initialize()
        await WorkflowRepository(database.sessions).complete_ide_task(workflow_id, second_id, "ok")
        await database.close()

    asyncio.run(tick())
    app.run()
    assert app.checkbox[1].value is True
    assert any("All tasks done" in markdown.value for markdown in app.markdown)


def test_dashboard_password_sign_in(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEFLUX_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'dashboard.db'}")
    monkeypatch.setenv("CODEFLUX_DASHBOARD_PASSWORD", "open-sesame")
    monkeypatch.setenv("CODEFLUX_GATEWAY_KEYS", "admin-secret:admin")
    app = AppTest.from_file(Path(__file__).parents[1] / "streamlit_app.py", default_timeout=20).run()
    assert app.title[0].value == "Sign in to CodeFlux"
    app.text_input[0].input("wrong").run()
    app.button[0].click().run()
    assert app.error[0].value == "Incorrect dashboard password."
    app.text_input[0].input("open-sesame").run()
    app.button[0].click().run()
    assert not app.exception
    assert app.title[0].value == "CodeFlux"
    assert app.session_state.gateway_key == "admin-secret"
