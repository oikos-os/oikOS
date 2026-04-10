"""Tests for Docker Compose configuration — validates structure without running containers."""

import yaml
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


class TestDockerCompose:
    @pytest.fixture
    def compose(self):
        path = PROJECT_ROOT / "docker-compose.yml"
        assert path.exists(), "docker-compose.yml not found at project root"
        return yaml.safe_load(path.read_text())

    def test_three_services(self, compose):
        assert set(compose["services"].keys()) == {"oikos-core", "ollama", "searxng"}

    def test_all_ports_localhost_only(self, compose):
        for name, svc in compose["services"].items():
            for port in svc.get("ports", []):
                assert port.startswith("127.0.0.1:"), f"{name} port {port} not localhost-only"

    def test_oikos_core_depends_on_ollama_and_searxng(self, compose):
        deps = compose["services"]["oikos-core"]["depends_on"]
        assert "ollama" in deps
        assert "searxng" in deps

    def test_ollama_has_gpu_reservation(self, compose):
        ollama = compose["services"]["ollama"]
        devices = ollama["deploy"]["resources"]["reservations"]["devices"]
        assert any("gpu" in d.get("capabilities", []) for d in devices)

    def test_ollama_has_healthcheck(self, compose):
        assert "healthcheck" in compose["services"]["ollama"]

    def test_searxng_has_healthcheck(self, compose):
        assert "healthcheck" in compose["services"]["searxng"]

    def test_searxng_telemetry_disabled(self, compose):
        env = compose["services"]["searxng"]["environment"]
        assert "SEARXNG_TELEMETRY=false" in env

    def test_named_volumes_for_persistence(self, compose):
        assert "ollama_models" in compose.get("volumes", {})

    def test_oikos_core_mounts_vault(self, compose):
        volumes = compose["services"]["oikos-core"]["volumes"]
        vault_mount = [v for v in volumes if "vault" in v and "/app/vault" in v]
        assert vault_mount, "Vault not mounted in oikos-core"

    def test_all_services_restart_policy(self, compose):
        for name, svc in compose["services"].items():
            assert svc.get("restart") == "unless-stopped", f"{name} missing restart policy"


class TestDockerfile:
    def test_dockerfile_exists(self):
        assert (PROJECT_ROOT / "Dockerfile").exists()

    def test_dockerfile_exposes_correct_ports(self):
        content = (PROJECT_ROOT / "Dockerfile").read_text()
        assert "EXPOSE 8420" in content or "EXPOSE 8420 8421" in content

    def test_dockerfile_has_healthcheck(self):
        content = (PROJECT_ROOT / "Dockerfile").read_text()
        assert "HEALTHCHECK" in content

    def test_dockerfile_uses_python_312(self):
        content = (PROJECT_ROOT / "Dockerfile").read_text()
        assert "python:3.12" in content

    def test_dockerignore_exists(self):
        assert (PROJECT_ROOT / ".dockerignore").exists()

    def test_dockerignore_excludes_venv(self):
        content = (PROJECT_ROOT / ".dockerignore").read_text()
        assert ".venv" in content

    def test_dockerignore_excludes_git(self):
        content = (PROJECT_ROOT / ".dockerignore").read_text()
        assert ".git" in content

    def test_dockerignore_excludes_env(self):
        content = (PROJECT_ROOT / ".dockerignore").read_text()
        assert ".env" in content

    def test_dockerfile_is_multistage(self):
        content = (PROJECT_ROOT / "Dockerfile").read_text()
        assert content.count("FROM ") >= 2, "Dockerfile should use multi-stage build"

    def test_all_dependencies_use_service_healthy(self):
        path = PROJECT_ROOT / "docker-compose.yml"
        compose = yaml.safe_load(path.read_text())
        deps = compose["services"]["oikos-core"]["depends_on"]
        for svc_name, dep_config in deps.items():
            if isinstance(dep_config, dict):
                assert dep_config.get("condition") == "service_healthy", \
                    f"{svc_name} should use service_healthy condition"


class TestHealthCheck:
    def test_healthcheck_script_exists(self):
        assert (PROJECT_ROOT / "docker" / "healthcheck.py").exists()

    def test_healthcheck_is_importable(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "healthcheck", PROJECT_ROOT / "docker" / "healthcheck.py"
        )
        assert spec is not None
