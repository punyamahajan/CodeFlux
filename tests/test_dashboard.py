from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_dashboard_renders(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEFLUX_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'dashboard.db'}")
    monkeypatch.setenv("CODEFLUX_DASHBOARD_PASSWORD", "")
    app = AppTest.from_file(Path(__file__).parents[1] / "streamlit_app.py", default_timeout=10).run()
    assert not app.exception
    assert app.title[0].value == "CodeFlux control room"
    assert len(app.tabs) == 4
