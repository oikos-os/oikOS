"""Tests for provider config loader."""

import pytest
from pathlib import Path

from core.cognition.providers.config_loader import (
    load_providers_config,
    generate_default_config,
    ConfigError,
)


VALID_TOML = """\
[general]
default = "local"
posture = "balanced"

[providers.local]
type = "ollama"
base_url = "http://localhost:11434"
default_model = "qwen2.5:14b"
timeout = 60

[providers.claude]
type = "anthropic"
default_model = "claude-sonnet-4-20250514"
"""


class TestLoadValidToml:
    def test_parses_structure(self, tmp_path):
        f = tmp_path / "providers.toml"
        f.write_text(VALID_TOML)
        config = load_providers_config(f)
        assert config["general"]["default"] == "local"
        assert "local" in config["providers"]
        assert "claude" in config["providers"]
        assert config["providers"]["local"]["type"] == "ollama"

    def test_fills_defaults_for_missing_sections(self, tmp_path):
        f = tmp_path / "providers.toml"
        f.write_text(VALID_TOML)
        config = load_providers_config(f)
        assert "model_tiers" in config
        assert "costs" in config
        assert config["general"]["fallback"] == "local"


class TestMissingFile:
    def test_returns_defaults(self, tmp_path):
        config = load_providers_config(tmp_path / "nonexistent.toml")
        assert config["general"]["default"] == "local"
        assert "local" in config["providers"]
        assert config["providers"]["local"]["type"] == "ollama"

    def test_defaults_have_model_tiers(self, tmp_path):
        config = load_providers_config(tmp_path / "nonexistent.toml")
        assert "simple" in config["model_tiers"]
        assert "moderate" in config["model_tiers"]
        assert "complex" in config["model_tiers"]


class TestValidation:
    def test_invalid_type_raises(self, tmp_path):
        f = tmp_path / "providers.toml"
        f.write_text('[general]\ndefault = "bad"\n[providers.bad]\ntype = "unknown"\n')
        with pytest.raises(ConfigError, match="invalid type"):
            load_providers_config(f)

    def test_missing_type_raises(self, tmp_path):
        f = tmp_path / "providers.toml"
        f.write_text('[general]\ndefault = "x"\n[providers.x]\nmodel = "foo"\n')
        with pytest.raises(ConfigError, match="missing required 'type'"):
            load_providers_config(f)

    def test_invalid_posture_raises(self, tmp_path):
        f = tmp_path / "providers.toml"
        f.write_text('[general]\nposture = "yolo"\n[providers.local]\ntype = "ollama"\n')
        with pytest.raises(ConfigError, match="Invalid posture"):
            load_providers_config(f)

    def test_invalid_default_raises(self, tmp_path):
        f = tmp_path / "providers.toml"
        f.write_text('[general]\ndefault = "nonexistent"\n[providers.local]\ntype = "ollama"\n')
        with pytest.raises(ConfigError, match="not defined"):
            load_providers_config(f)

    def test_malformed_toml_raises(self, tmp_path):
        f = tmp_path / "providers.toml"
        f.write_text("this is not valid toml [[[")
        with pytest.raises(ConfigError, match="Malformed"):
            load_providers_config(f)


class TestGenerateDefault:
    def test_creates_file(self, tmp_path):
        path = generate_default_config(tmp_path / "providers.toml")
        assert path.exists()
        content = path.read_text()
        assert "[general]" in content
        assert "[providers.local]" in content

    def test_does_not_overwrite_existing(self, tmp_path):
        f = tmp_path / "providers.toml"
        f.write_text("existing content")
        generate_default_config(f)
        assert f.read_text() == "existing content"

    def test_generated_config_is_loadable(self, tmp_path):
        path = generate_default_config(tmp_path / "providers.toml")
        config = load_providers_config(path)
        assert config["general"]["default"] == "local"
        assert config["providers"]["local"]["type"] == "ollama"


class TestMinimalToml:
    def test_only_general_and_one_provider(self, tmp_path):
        f = tmp_path / "providers.toml"
        f.write_text('[general]\ndefault = "local"\n[providers.local]\ntype = "ollama"\n')
        config = load_providers_config(f)
        assert config["general"]["default"] == "local"
        assert "model_tiers" in config
        assert "costs" in config
