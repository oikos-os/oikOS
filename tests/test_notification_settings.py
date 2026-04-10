"""T-119 Task 6: Test notification settings registration and gating."""
from __future__ import annotations

import pytest

from core.interface.settings_registry import (
    SETTINGS_REGISTRY,
    SettingTier,
    validate_setting,
)


class TestNotificationSettingsRegistry:
    def test_must_enabled_setting_exists(self):
        assert "notifications_must_enabled" in SETTINGS_REGISTRY
        defn = SETTINGS_REGISTRY["notifications_must_enabled"]
        assert defn.tier == SettingTier.ADVANCED
        assert defn.setting_type == "bool"
        assert defn.default is True

    def test_should_enabled_setting_exists(self):
        assert "notifications_should_enabled" in SETTINGS_REGISTRY
        defn = SETTINGS_REGISTRY["notifications_should_enabled"]
        assert defn.tier == SettingTier.ADVANCED
        assert defn.setting_type == "bool"
        assert defn.default is True

    def test_desktop_enabled_setting_exists(self):
        assert "notifications_desktop_enabled" in SETTINGS_REGISTRY
        defn = SETTINGS_REGISTRY["notifications_desktop_enabled"]
        assert defn.tier == SettingTier.ADVANCED
        assert defn.setting_type == "bool"
        assert defn.default is True

    def test_validate_must_enabled_boolean(self):
        ok, _ = validate_setting("notifications_must_enabled", True)
        assert ok is True
        ok, _ = validate_setting("notifications_must_enabled", "not a bool")
        assert ok is False

    def test_existing_notifications_master_still_exists(self):
        """The pre-existing 'notifications' master key is untouched."""
        assert "notifications" in SETTINGS_REGISTRY
        assert SETTINGS_REGISTRY["notifications"].tier == SettingTier.ESSENTIAL
        assert SETTINGS_REGISTRY["notifications"].default is True


class TestNotificationManagerGating:
    def test_manager_respects_notifications_master_off(self, monkeypatch):
        """When master notifications=False, NO tier fires — including MUST."""
        from core.autonomic.notifications import NotificationManager
        from core.interface import settings as settings_module

        def fake_get_setting(key, default=None):
            if key == "notifications":
                return False
            return default if default is not None else True

        monkeypatch.setattr(settings_module, "get_setting", fake_get_setting)

        mgr = NotificationManager()
        captured = []
        mgr._dispatch_fn = lambda msg, title, sev, timeout, key: captured.append(msg)

        # MUST-tier event
        mgr.handle_event({"category": "safety", "type": "pii_anonymized",
                          "data": {"entity_count": 1}})
        assert captured == [], f"MUST event should have been suppressed when master=False, got {captured}"

    def test_manager_respects_must_disabled(self, monkeypatch):
        """When notifications_must_enabled=False, MUST tier is suppressed."""
        from core.autonomic.notifications import NotificationManager
        from core.interface import settings as settings_module

        def fake_get_setting(key, default=None):
            if key == "notifications":
                return True
            if key == "notifications_must_enabled":
                return False
            if key == "notifications_should_enabled":
                return True
            return default if default is not None else True

        monkeypatch.setattr(settings_module, "get_setting", fake_get_setting)

        mgr = NotificationManager()
        captured = []
        mgr._dispatch_fn = lambda msg, title, sev, timeout, key: captured.append(msg)

        # MUST tier — suppressed
        mgr.handle_event({"category": "safety", "type": "pii_anonymized",
                          "data": {"entity_count": 1}})
        # SHOULD tier — should still fire
        mgr.handle_event({"category": "daemon", "type": "budget_warning",
                          "data": {"usage_percent": 80}})

        assert len(captured) == 1, f"expected 1 (SHOULD only), got {captured}"
        assert "budget" in captured[0].lower()

    def test_manager_respects_should_disabled(self, monkeypatch):
        """When notifications_should_enabled=False, SHOULD tier is suppressed but MUST still fires."""
        from core.autonomic.notifications import NotificationManager
        from core.interface import settings as settings_module

        def fake_get_setting(key, default=None):
            if key == "notifications":
                return True
            if key == "notifications_should_enabled":
                return False
            if key == "notifications_must_enabled":
                return True
            return default if default is not None else True

        monkeypatch.setattr(settings_module, "get_setting", fake_get_setting)

        mgr = NotificationManager()
        captured = []
        mgr._dispatch_fn = lambda msg, title, sev, timeout, key: captured.append(msg)

        # MUST tier — fires
        mgr.handle_event({"category": "safety", "type": "pii_anonymized",
                          "data": {"entity_count": 1}})
        # SHOULD tier — suppressed
        mgr.handle_event({"category": "daemon", "type": "budget_warning",
                          "data": {"usage_percent": 80}})

        assert len(captured) == 1, f"expected 1 (MUST only), got {captured}"
        assert "PII" in captured[0]

    def test_manager_both_tiers_enabled_by_default(self, monkeypatch):
        """When all settings are True (the defaults), both MUST and SHOULD fire."""
        from core.autonomic.notifications import NotificationManager
        from core.interface import settings as settings_module

        def fake_get_setting(key, default=None):
            return True

        monkeypatch.setattr(settings_module, "get_setting", fake_get_setting)

        mgr = NotificationManager()
        captured = []
        mgr._dispatch_fn = lambda msg, title, sev, timeout, key: captured.append(msg)

        mgr.handle_event({"category": "safety", "type": "pii_anonymized",
                          "data": {"entity_count": 1}})
        mgr.handle_event({"category": "daemon", "type": "budget_warning",
                          "data": {"usage_percent": 80}})

        assert len(captured) == 2
