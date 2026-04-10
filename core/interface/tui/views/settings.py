"""Settings view — Essential, Advanced, and Connections sections."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll, Vertical
from textual.widget import Widget
from textual.widgets import Button, Input, RadioButton, RadioSet, Static, Switch


# widget ID → registry key
_INPUT_MAP: dict[str, str] = {
    "set-temperature": "inference_temperature",
    "set-max-tokens": "inference_max_tokens",
    "set-idle-timeout": "idle_timeout",
    "set-session-timeout": "session_timeout",
    "set-pii-threshold": "pii_confidence_threshold",
    "set-credit-cap": "credits_monthly_cap",
    "set-approval-timeout": "approval_timeout",
    "set-vault-weight": "vault_search_weight",
}

_SWITCH_MAP: dict[str, str] = {
    "sw-boot-quote": "boot_quote",
    "sw-notifications": "notifications",
}

_POSTURE_MAP: dict[int, str] = {
    0: "conservative",
    1: "balanced",
    2: "aggressive",
}

_POSTURE_INDEX: dict[str, int] = {v: k for k, v in _POSTURE_MAP.items()}


class SettingsView(Widget, can_focus=True):
    """Settings screen: essential knobs, advanced tuning, connections."""

    def compose(self) -> ComposeResult:
        yield Static("◈ Settings", id="settings-header")
        with VerticalScroll(id="settings-scroll"):

            # ── Essential ────────────────────────────────────────────
            with Vertical(id="settings-essential"):
                yield Static("essential", classes="section-label")
                yield Static("─" * 35, classes="section-separator")

                yield Static("routing posture", classes="setting-label")
                with RadioSet(id="posture-set"):
                    yield RadioButton("conservative", id="posture-conservative")
                    yield RadioButton("balanced", id="posture-balanced", value=True)
                    yield RadioButton("aggressive", id="posture-aggressive")
                yield Static(
                    "[dim]how aggressively queries route to cloud[/]",
                    classes="setting-hint",
                )

                yield Static("temperature", classes="setting-label")
                yield Input(value="0.7", id="set-temperature", type="number")
                yield Static("[dim]generation temperature (0.0 – 2.0)[/]", classes="setting-hint")

                yield Static("max tokens", classes="setting-label")
                yield Input(value="2048", id="set-max-tokens", type="integer")
                yield Static("[dim]max response tokens (256 – 32768)[/]", classes="setting-hint")

                yield Static("theme", classes="setting-label")
                with Horizontal(id="theme-buttons"):
                    yield Button("Amber", id="btn-theme-amber")
                    yield Button("Green", id="btn-theme-green")
                    yield Button("White", id="btn-theme-white")

                yield Static("idle timeout (min)", classes="setting-label")
                yield Input(value="15", id="set-idle-timeout", type="integer")
                yield Static("[dim]minutes before IDLE cascade (1 – 120)[/]", classes="setting-hint")

                yield Static("session timeout (min)", classes="setting-label")
                yield Input(value="30", id="set-session-timeout", type="integer")
                yield Static("[dim]minutes before session auto-close (5 – 180)[/]", classes="setting-hint")

                with Horizontal(classes="setting-toggle-row"):
                    yield Static("boot quote", classes="setting-label")
                    yield Switch(value=True, id="sw-boot-quote")
                yield Static("[dim]show doctrine quote on boot[/]", classes="setting-hint")

                with Horizontal(classes="setting-toggle-row"):
                    yield Static("notifications", classes="setting-label")
                    yield Switch(value=True, id="sw-notifications")
                yield Static("[dim]enable toast notifications[/]", classes="setting-hint")

            # ── Advanced ─────────────────────────────────────────────
            with Vertical(id="settings-advanced"):
                yield Static("advanced", classes="section-label")
                yield Static("─" * 35, classes="section-separator")

                yield Static("PII threshold", classes="setting-label")
                yield Input(value="0.3", id="set-pii-threshold", type="number")
                yield Static("[dim]PII detection confidence threshold (0.0 – 1.0)[/]", classes="setting-hint")

                yield Static("credit cap (tokens/month)", classes="setting-label")
                yield Input(value="1000000", id="set-credit-cap", type="number")
                yield Static("[dim]monthly cloud spending limit in tokens[/]", classes="setting-hint")

                yield Static("approval timeout (sec)", classes="setting-label")
                yield Input(value="300", id="set-approval-timeout", type="integer")
                yield Static("[dim]ASK_FIRST proposal expiry (30 – 3600)[/]", classes="setting-hint")

                yield Static("vault search weight", classes="setting-label")
                yield Input(value="0.7", id="set-vault-weight", type="number")
                yield Static("[dim]vector vs BM25 balance (0=all BM25, 1=all vector)[/]", classes="setting-hint")

            # ── Connections ──────────────────────────────────────────
            with Vertical(id="settings-providers"):
                yield Static("providers", classes="section-label")
                yield Static("─" * 35, classes="section-separator")
                yield Static("(loading...)", id="provider-list")

            with Vertical(id="settings-claude"):
                yield Static("claude", classes="section-label")
                yield Static("─" * 35, classes="section-separator")
                yield Static("(loading...)", id="claude-status")

            with Vertical(id="settings-google"):
                yield Static("google services", classes="section-label")
                yield Static("─" * 35, classes="section-separator")
                yield Static("(loading...)", id="google-service-list")

    def on_mount(self) -> None:
        self.run_worker(self._load_settings(), exclusive=False)

    async def _load_settings(self) -> None:
        """Fetch current settings from API and populate widgets."""
        if not hasattr(self.app, "api_client"):
            return
        data = await self.app.api_client.settings()
        essential = data.get("essential", {})
        advanced = data.get("advanced", {})

        def _val(section: dict, key: str):
            entry = section.get(key, {})
            return entry.get("value") if isinstance(entry, dict) else entry

        posture = _val(essential, "cloud_routing_posture") or "balanced"
        idx = _POSTURE_INDEX.get(posture, 1)
        try:
            radio_set = self.query_one("#posture-set", RadioSet)
            buttons = list(radio_set.query(RadioButton))
            if 0 <= idx < len(buttons):
                buttons[idx].value = True
        except Exception:
            pass

        _input_defaults = {
            "set-temperature": _val(essential, "inference_temperature"),
            "set-max-tokens": _val(essential, "inference_max_tokens"),
            "set-idle-timeout": _val(essential, "idle_timeout"),
            "set-session-timeout": _val(essential, "session_timeout"),
            "set-pii-threshold": _val(advanced, "pii_confidence_threshold"),
            "set-credit-cap": _val(advanced, "credits_monthly_cap"),
            "set-approval-timeout": _val(advanced, "approval_timeout"),
            "set-vault-weight": _val(advanced, "vault_search_weight"),
        }
        for widget_id, value in _input_defaults.items():
            if value is None:
                continue
            try:
                self.query_one(f"#{widget_id}", Input).value = str(value)
            except Exception:
                pass

        _switch_defaults = {
            "sw-boot-quote": _val(essential, "boot_quote"),
            "sw-notifications": _val(essential, "notifications"),
        }
        for widget_id, value in _switch_defaults.items():
            if value is None:
                continue
            try:
                self.query_one(f"#{widget_id}", Switch).value = bool(value)
            except Exception:
                pass

    async def _save_setting(self, key: str, value) -> None:
        """Write a setting via API and show toast feedback."""
        if not hasattr(self.app, "api_client"):
            return
        result = await self.app.api_client.update_setting(key, value)
        if result.get("restart_required"):
            self.notify(f"{key} saved — restart required", severity="warning")
        elif result.get("applied"):
            self.notify(f"{key} saved", severity="information")

    # ── Event handlers ────────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        key = _INPUT_MAP.get(event.input.id or "")
        if not key:
            return
        raw = event.value.strip()
        if not raw:
            return
        # Coerce to appropriate type
        try:
            value: float | int = float(raw) if "." in raw else int(raw)
        except ValueError:
            self.notify(f"Invalid value for {key}", severity="error")
            return
        self.run_worker(self._save_setting(key, value), exclusive=False)

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id != "posture-set":
            return
        idx = event.index
        posture = _POSTURE_MAP.get(idx)
        if posture:
            self.run_worker(self._save_setting("cloud_routing_posture", posture), exclusive=False)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        key = _SWITCH_MAP.get(event.switch.id or "")
        if not key:
            return
        self.run_worker(self._save_setting(key, event.value), exclusive=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        theme_map = {
            "btn-theme-amber": "amber",
            "btn-theme-green": "green",
            "btn-theme-white": "white",
        }
        theme_name = theme_map.get(event.button.id, "")
        if not theme_name:
            return
        self._apply_theme(theme_name)

    def _apply_theme(self, theme_name: str) -> None:
        self.run_worker(self.app.api_client.update_setting("theme", theme_name))
        screen = self.app.screen
        screen.remove_class("theme-amber", "theme-green", "theme-white")
        if theme_name != "amber":
            screen.add_class(f"theme-{theme_name}")
        self.notify(f"Theme: {theme_name}")

    # ── External update methods (called by app polling loop) ─────────────────

    def update_providers(self, models: dict) -> None:
        """Update provider list from /api/models response."""
        providers: dict[str, bool] = {}
        for category, model_list in models.items():
            if not isinstance(model_list, list):
                continue
            if category == "local" and model_list:
                providers["local (Ollama)"] = True
            for m in model_list:
                if isinstance(m, dict) and m.get("provider"):
                    name = m["provider"]
                    providers[name] = True
        if providers:
            lines = [f"{name}  ● connected" for name in providers]
        else:
            lines = ["No providers detected"]
        self.query_one("#provider-list", Static).update("\n".join(lines))

    def update_claude(self, claude_status: dict) -> None:
        """Update Claude OAuth status."""
        if claude_status.get("connected"):
            text = "Claude OAuth  ● connected"
        else:
            text = "Claude OAuth  ○ not connected"
        self.query_one("#claude-status", Static).update(text)

    def update_google(self, google_status: dict) -> None:
        """Update Google services status."""
        from core.interface.tui.client import scopes_to_services

        if google_status.get("connected"):
            services = scopes_to_services(google_status.get("scopes", []))
            if services:
                lines = [f"{svc}  ● connected" for svc in services]
            else:
                lines = ["connected (no services detected)"]
        else:
            lines = ["not connected ○"]
        self.query_one("#google-service-list", Static).update("\n".join(lines))
