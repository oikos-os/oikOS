import json
import pytest


class TestOnboardingState:
    def test_fresh_install_not_complete(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.interface.settings.SETTINGS_FILE", tmp_path / "settings.json")
        import core.interface.settings as s
        s._loaded = False
        s._overrides.clear()
        from core.onboarding.state import is_onboarding_complete
        assert is_onboarding_complete() is False

    def test_mark_complete(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.interface.settings.SETTINGS_FILE", tmp_path / "settings.json")
        import core.interface.settings as s
        s._loaded = False
        s._overrides.clear()
        from core.onboarding.state import mark_onboarding_complete, is_onboarding_complete
        mark_onboarding_complete()
        assert is_onboarding_complete() is True

    def test_step_tracking(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.interface.settings.SETTINGS_FILE", tmp_path / "settings.json")
        import core.interface.settings as s
        s._loaded = False
        s._overrides.clear()
        from core.onboarding.state import get_step, advance_step
        assert get_step() == 0
        advance_step()
        assert get_step() == 1

    def test_resume_from_last_step(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.interface.settings.SETTINGS_FILE", tmp_path / "settings.json")
        import core.interface.settings as s
        s._loaded = False
        s._overrides.clear()
        from core.onboarding.state import advance_step, get_step
        advance_step()  # 0 -> 1
        advance_step()  # 1 -> 2
        # Simulate restart
        s._loaded = False
        s._overrides.clear()
        assert get_step() == 2

    def test_existing_installation_skips(self, tmp_path, monkeypatch):
        (tmp_path / "settings.json").write_text(json.dumps({"onboarding_complete": True}))
        monkeypatch.setattr("core.interface.settings.SETTINGS_FILE", tmp_path / "settings.json")
        import core.interface.settings as s
        s._loaded = False
        s._overrides.clear()
        from core.onboarding.state import is_onboarding_complete
        assert is_onboarding_complete() is True
