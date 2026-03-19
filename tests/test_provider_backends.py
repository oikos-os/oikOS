import pytest
from unittest.mock import patch  # noqa: F401


class TestOpenAILocalProvider:
    def test_openai_local_in_provider_map(self):
        from core.cognition.providers.bootstrap import _PROVIDER_MAP
        assert "openai-local" in _PROVIDER_MAP

    def test_openai_local_no_env_key_required(self):
        from core.cognition.providers.bootstrap import _PROVIDER_MAP
        _, _, env_key = _PROVIDER_MAP["openai-local"]
        assert env_key is None

    def test_openai_local_uses_openai_provider_class(self):
        from core.cognition.providers.bootstrap import _PROVIDER_MAP
        module_path, class_name, _ = _PROVIDER_MAP["openai-local"]
        assert "openai_provider" in module_path
        assert class_name == "OpenAIProvider"

    def test_toml_with_openai_local_registers(self, tmp_path, monkeypatch):
        """providers.toml entry with type=openai-local registers without API key."""
        toml_content = '[general]\ndefault = "lmstudio"\n\n[providers.lmstudio]\ntype = "openai-local"\nbase_url = "http://localhost:1234/v1"\ndefault_model = "mistral-7b"\n'
        toml_file = tmp_path / "providers.toml"
        toml_file.write_text(toml_content)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from core.cognition.providers.config_loader import load_providers_config
        from core.cognition.providers.bootstrap import _create_registry_from_config
        config = load_providers_config(toml_file)
        registry = _create_registry_from_config(config)
        assert "lmstudio" in registry.list_all()


class TestBackendDisplayNames:
    def test_all_backends_have_display_names(self):
        from core.onboarding.detector import BACKEND_DISPLAY_NAMES, BACKENDS
        for b in BACKENDS:
            assert b["name"] in BACKEND_DISPLAY_NAMES

    def test_display_name_values(self):
        from core.onboarding.detector import BACKEND_DISPLAY_NAMES
        assert BACKEND_DISPLAY_NAMES["lm-studio"] == "LM Studio"
        assert BACKEND_DISPLAY_NAMES["vllm"] == "vLLM"
        assert BACKEND_DISPLAY_NAMES["llama-cpp"] == "llama.cpp Server"
        assert BACKEND_DISPLAY_NAMES["tabbyapi"] == "ExLlamaV2 (TabbyAPI)"

    def test_probe_includes_display_name(self):
        from core.onboarding.detector import BACKEND_DISPLAY_NAMES, BACKENDS
        for b in BACKENDS:
            display = BACKEND_DISPLAY_NAMES[b["name"]]
            assert isinstance(display, str) and len(display) > 0


class TestMultiBackendToml:
    def test_writes_all_detected_backends(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.onboarding.manager.PROVIDERS_TOML", tmp_path / "providers.toml")
        from core.onboarding.manager import write_providers_toml
        detected = [
            {"backend": "ollama", "port": 11434, "models": [{"name": "qwen2.5:14b"}]},
            {"backend": "lm-studio", "port": 1234, "models": [{"name": "mistral-7b"}]},
        ]
        write_providers_toml(local_provider="ollama", local_model="qwen2.5:14b", detected_backends=detected)
        content = (tmp_path / "providers.toml").read_text()
        assert "[providers.ollama]" in content
        assert "[providers.lm-studio]" in content
        assert "localhost:1234" in content

    def test_non_ollama_gets_openai_local_type(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.onboarding.manager.PROVIDERS_TOML", tmp_path / "providers.toml")
        from core.onboarding.manager import write_providers_toml
        detected = [
            {"backend": "vllm", "port": 8000, "models": [{"name": "meta-llama/Llama-3-8B"}]},
        ]
        write_providers_toml(local_provider="vllm", local_model="meta-llama/Llama-3-8B", detected_backends=detected)
        content = (tmp_path / "providers.toml").read_text()
        assert 'type = "openai-local"' in content

    def test_ollama_has_no_type_field(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.onboarding.manager.PROVIDERS_TOML", tmp_path / "providers.toml")
        from core.onboarding.manager import write_providers_toml
        detected = [
            {"backend": "ollama", "port": 11434, "models": [{"name": "qwen2.5:14b"}]},
        ]
        write_providers_toml(local_provider="ollama", local_model="qwen2.5:14b", detected_backends=detected)
        content = (tmp_path / "providers.toml").read_text()
        assert "[providers.ollama]" in content
        assert "type" not in content

    def test_fallback_when_no_detected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.onboarding.manager.PROVIDERS_TOML", tmp_path / "providers.toml")
        from core.onboarding.manager import write_providers_toml
        write_providers_toml(local_provider="ollama", local_model="qwen2.5:14b", detected_backends=None)
        content = (tmp_path / "providers.toml").read_text()
        assert "[providers.ollama]" in content

    def test_default_provider_matches_selection(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.onboarding.manager.PROVIDERS_TOML", tmp_path / "providers.toml")
        from core.onboarding.manager import write_providers_toml
        detected = [
            {"backend": "ollama", "port": 11434, "models": [{"name": "qwen2.5:14b"}]},
            {"backend": "lm-studio", "port": 1234, "models": [{"name": "mistral-7b"}]},
        ]
        write_providers_toml(local_provider="lm-studio", local_model="mistral-7b", detected_backends=detected)
        content = (tmp_path / "providers.toml").read_text()
        assert 'default_provider = "lm-studio"' in content

    def test_skips_unknown_backend(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.onboarding.manager.PROVIDERS_TOML", tmp_path / "providers.toml")
        from core.onboarding.manager import write_providers_toml
        detected = [
            {"backend": "unknown-server", "port": 9999, "models": [{"name": "test"}]},
            {"backend": "ollama", "port": 11434, "models": [{"name": "qwen2.5:14b"}]},
        ]
        write_providers_toml(local_provider="ollama", local_model="qwen2.5:14b", detected_backends=detected)
        content = (tmp_path / "providers.toml").read_text()
        assert "unknown-server" not in content
        assert "[providers.ollama]" in content

    def test_unsafe_model_name_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.onboarding.manager.PROVIDERS_TOML", tmp_path / "providers.toml")
        from core.onboarding.manager import write_providers_toml
        detected = [
            {"backend": "ollama", "port": 11434, "models": [{"name": 'evil"; rm -rf /'}]},
        ]
        write_providers_toml(local_provider="ollama", local_model="qwen2.5:14b", detected_backends=detected)
        content = (tmp_path / "providers.toml").read_text()
        assert "evil" not in content
        assert 'default_model = "unknown"' in content
