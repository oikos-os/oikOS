import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr("core.interface.settings.SETTINGS_FILE", tmp_path / "settings.json")
    import core.interface.settings as s
    s._loaded = False
    s._overrides.clear()
    yield


@pytest.fixture(autouse=True)
def reset_rooms():
    yield
    from core.rooms.manager import reset_room_manager
    reset_room_manager()


@pytest.fixture
def client():
    from core.interface.api.server import create_app
    return TestClient(create_app(dev=True))


class TestOnboardingAPI:
    def test_status_fresh_install(self, client):
        resp = client.get("/api/onboarding/status")
        assert resp.status_code == 200
        assert resp.json()["complete"] is False
        assert resp.json()["step"] == 0

    def test_save_identity(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("core.onboarding.identity.VAULT_DIR", tmp_path)
        monkeypatch.setattr("core.memory.indexer.index_vault", lambda **kw: {"added": 0})
        resp = client.post("/api/onboarding/identity", json={"name": "Test User", "description": "A test"})
        assert resp.status_code == 200
        assert (tmp_path / "identity" / "IDENTITY.md").exists()

    def test_save_identity_empty_name_fails(self, client):
        resp = client.post("/api/onboarding/identity", json={"name": "", "description": ""})
        assert resp.status_code == 400

    def test_detect_backends(self, client):
        resp = client.get("/api/onboarding/detect-backends")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_save_model(self, client):
        resp = client.post("/api/onboarding/model", json={"provider": "ollama", "model": "qwen2.5:14b"})
        assert resp.status_code == 200

    def test_save_provider_key(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("core.onboarding.manager.ENV_FILE", tmp_path / ".env")
        resp = client.post("/api/onboarding/providers", json={"provider": "anthropic", "api_key": "sk-ant-test123"})
        assert resp.status_code == 200
        assert "ANTHROPIC_API_KEY=sk-ant-test123" in (tmp_path / ".env").read_text()

    def test_test_provider_connection(self, client):
        resp = client.post("/api/onboarding/providers/test", json={"provider": "anthropic", "api_key": "sk-ant-test"})
        assert resp.status_code in (200, 400)

    def test_complete_onboarding(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("core.onboarding.manager.PROVIDERS_TOML", tmp_path / "providers.toml")
        resp = client.post("/api/onboarding/complete")
        assert resp.status_code == 200
        status = client.get("/api/onboarding/status").json()
        assert status["complete"] is True

    def test_create_room_from_template(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        resp = client.post("/api/onboarding/rooms", json={"template": "researcher"})
        assert resp.status_code == 200

    def test_no_auth_required(self, client):
        resp = client.get("/api/onboarding/status")
        assert resp.status_code == 200  # Not 401/403
