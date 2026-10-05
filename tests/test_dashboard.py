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
    assert len(app.tabs) == 4
    assert any(selectbox.label == "Model for checklist" for selectbox in app.selectbox)
    assert any("One place to plan, route, and complete work" in markdown.value for markdown in app.markdown)
    assert any(subheader.value == "Continue in your IDE" for subheader in app.subheader)
    assert not any(button.label == "Do the work" for button in app.button)
