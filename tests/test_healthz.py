import json

import pytest
from fastapi.testclient import TestClient

from codeflux.app import create_app
from codeflux.settings import Settings


@pytest.fixture
def client(tmp_path):
    config_path = tmp_path / "routes.yaml"
    config_path.write_text(
        json.dumps({"routes": {"smart": {"candidates": [{"provider": "openai", "model": "m"}]}}})
    )
    settings = Settings(
        _env_file=None,
        config_path=config_path,
        gateway_keys="secret-key:admin",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_healthz_endpoint(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "codeflux"}
