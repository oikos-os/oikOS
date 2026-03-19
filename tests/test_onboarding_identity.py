import pytest
from pathlib import Path
from unittest.mock import patch


class TestIdentityBootstrapper:
    def test_creates_identity_file(self, tmp_path):
        from core.onboarding.identity import bootstrap_identity
        with patch("core.memory.indexer.index_vault"):
            bootstrap_identity("Alice", "software engineer", vault_dir=tmp_path)
        identity = tmp_path / "identity" / "IDENTITY.md"
        assert identity.exists()
        content = identity.read_text(encoding="utf-8")
        assert "Alice" in content
        assert "tier: CORE" in content

    def test_creates_mission_template(self, tmp_path):
        from core.onboarding.identity import bootstrap_identity
        with patch("core.memory.indexer.index_vault"):
            bootstrap_identity("Test User", vault_dir=tmp_path)
        mission = tmp_path / "identity" / "MISSION.md"
        assert mission.exists()
        assert "What are you building?" in mission.read_text(encoding="utf-8")

    def test_does_not_overwrite_existing(self, tmp_path):
        identity_dir = tmp_path / "identity"
        identity_dir.mkdir(parents=True)
        existing = identity_dir / "IDENTITY.md"
        existing.write_text("# Existing identity\nDo not overwrite.")
        from core.onboarding.identity import bootstrap_identity
        with patch("core.memory.indexer.index_vault"):
            bootstrap_identity("New User", vault_dir=tmp_path)
        assert "Existing identity" in existing.read_text(encoding="utf-8")

    def test_name_required(self):
        from core.onboarding.identity import bootstrap_identity
        with pytest.raises(ValueError):
            bootstrap_identity("", vault_dir=Path("/tmp"))
        with pytest.raises(ValueError):
            bootstrap_identity("   ", vault_dir=Path("/tmp"))

    def test_name_max_length(self):
        from core.onboarding.identity import bootstrap_identity
        with pytest.raises(ValueError):
            bootstrap_identity("A" * 65, vault_dir=Path("/tmp"))

    def test_optional_description(self, tmp_path):
        from core.onboarding.identity import bootstrap_identity
        with patch("core.memory.indexer.index_vault"):
            bootstrap_identity("MinimalUser", vault_dir=tmp_path)
        content = (tmp_path / "identity" / "IDENTITY.md").read_text(encoding="utf-8")
        assert "MinimalUser" in content

    def test_triggers_vault_reindex(self, tmp_path):
        from core.onboarding.identity import bootstrap_identity
        with patch("core.memory.indexer.index_vault") as mock_index:
            bootstrap_identity("IndexUser", vault_dir=tmp_path)
            mock_index.assert_called_once()
