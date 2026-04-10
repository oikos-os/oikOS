"""Unit tests for resolve_generation_params — precedence chain: per-query > Room > Global.

Also: integration tests verifying resolved params flow into dispatch_blocking
and dispatch_streaming via route_kwargs and local inference kwargs.
"""

from unittest.mock import MagicMock, patch

import pytest

from core.cognition.pipeline.dispatch import resolve_generation_params


def _mock_room(temperature=None, max_tokens=None):
    room = MagicMock()
    room.voice.temperature = temperature
    room.limits.max_tokens_per_query = max_tokens
    return room


def _settings_side_effect(key):
    return {"inference_temperature": 0.7, "inference_max_tokens": 2048}[key]


@patch("core.cognition.pipeline.dispatch.get_setting", side_effect=_settings_side_effect)
def test_no_room_params_uses_global(mock_get_setting):
    room = _mock_room(temperature=None, max_tokens=None)
    temp, tokens = resolve_generation_params(room)
    assert temp == 0.7
    assert tokens == 2048


@patch("core.cognition.pipeline.dispatch.get_setting", side_effect=_settings_side_effect)
def test_room_temperature_overrides_global(mock_get_setting):
    room = _mock_room(temperature=0.9, max_tokens=None)
    temp, tokens = resolve_generation_params(room)
    assert temp == 0.9
    assert tokens == 2048


@patch("core.cognition.pipeline.dispatch.get_setting", side_effect=_settings_side_effect)
def test_room_max_tokens_overrides_global(mock_get_setting):
    room = _mock_room(temperature=None, max_tokens=4096)
    temp, tokens = resolve_generation_params(room)
    assert temp == 0.7
    assert tokens == 4096


@patch("core.cognition.pipeline.dispatch.get_setting", side_effect=_settings_side_effect)
def test_no_room_uses_global(mock_get_setting):
    temp, tokens = resolve_generation_params(None)
    assert temp == 0.7
    assert tokens == 2048


# ---------------------------------------------------------------------------
# Integration tests: resolved params flow into dispatch_blocking / dispatch_streaming
# ---------------------------------------------------------------------------

from core.cognition.pipeline import PreparedContext
from core.interface.models import (
    CompletionResponse,
    CompiledContext,
    ConfidenceResult,
    PIIResult,
    RoutingDecision,
    RouteType,
)
from core.cognition.pipeline import PostProcessResult


def _make_prep(route=RouteType.LOCAL) -> PreparedContext:
    """Build a minimal PreparedContext for dispatch tests."""
    decision = RoutingDecision(
        route=route, reason="test",
        confidence=ConfidenceResult(score=0.9, method="test"),
        pii_detected=False, query_hash="abc123", timestamp="2026-01-01T00:00:00",
    )
    pii = PIIResult(has_pii=False, entities=[])
    compiled = CompiledContext(query="hello", slices=[], total_tokens=10, budget=2048)
    return PreparedContext(
        decision=decision, pii_result=pii, effective_query="hello",
        pii_scrubbed=False, compiled=compiled, context_block="",
        system_prompt=None, full_prompt="hello", session={"session_id": "s1", "started_at": "t0"},
        qhash="abc123",
    )


def _dispatch_settings(key):
    """Settings lookup used by dispatch functions."""
    _map = {
        "inference_temperature": 0.7,
        "inference_max_tokens": 2048,
        "provider_default": "local",
        "provider_cloud_default": "gemini",
        "inference_model": "qwen2.5:14b",
        "cloud_routing_posture": "balanced",
    }
    return _map.get(key, "")


_POST = PostProcessResult(
    text="ok",
    confidence=ConfidenceResult(score=0.9, method="test"),
    contradiction=None,
    warnings=[],
    is_hard_veto=False,
)


class TestDispatchBlockingParams:
    """Verify resolved generation params reach the provider router and local fallback."""

    @patch("core.cognition.pipeline.dispatch.log_interaction_complete")
    @patch("core.cognition.pipeline.dispatch.log_routing_decision")
    @patch("core.cognition.pipeline.dispatch.post_process", return_value=_POST)
    @patch("core.cognition.pipeline.dispatch.get_provider_router")
    @patch("core.rooms.manager.get_room_manager")
    @patch("core.cognition.pipeline.dispatch.get_setting", side_effect=_dispatch_settings)
    def test_room_temperature_flows_to_provider(
        self, mock_settings, mock_rm, mock_router_fn, mock_pp, mock_log_route, mock_log_int,
    ):
        # Room with temp 0.9
        room = _mock_room(temperature=0.9, max_tokens=None)
        room.allowed_providers = None
        room.model.model = None
        room.model.provider = "anthropic"
        mock_rm.return_value.get_active_room.return_value = room

        # Override provider_default so we enter the provider block
        def _settings_with_provider(key):
            if key == "provider_default":
                return "anthropic"
            return _dispatch_settings(key)
        mock_settings.side_effect = _settings_with_provider

        router = MagicMock()
        router.route.return_value = CompletionResponse(
            text="hi", model="claude-3", provider="anthropic",
            input_tokens=10, output_tokens=5, latency_ms=100,
        )
        mock_router_fn.return_value = router

        prep = _make_prep(route=RouteType.CLOUD)
        trace = MagicMock()
        trace.to_dict.return_value = {}
        from core.cognition.pipeline.dispatch import dispatch_blocking
        dispatch_blocking(prep, trace=trace)

        # Verify temperature=0.9 was passed in route kwargs
        _, kwargs = router.route.call_args
        assert kwargs["temperature"] == 0.9
        assert kwargs["max_tokens"] == 2048

    @patch("core.cognition.pipeline.dispatch.log_interaction_complete")
    @patch("core.cognition.pipeline.dispatch.log_routing_decision")
    @patch("core.cognition.pipeline.dispatch.post_process", return_value=_POST)
    @patch("core.cognition.pipeline.dispatch.generate_local")
    @patch("core.rooms.manager.get_room_manager")
    @patch("core.cognition.pipeline.dispatch.get_setting", side_effect=_dispatch_settings)
    def test_room_params_flow_to_local_inference(
        self, mock_settings, mock_rm, mock_gen_local, mock_pp, mock_log_route, mock_log_int,
    ):
        room = _mock_room(temperature=0.3, max_tokens=1024)
        room.allowed_providers = None
        room.model.model = None
        room.model.provider = None
        mock_rm.return_value.get_active_room.return_value = room

        mock_gen_local.return_value = {"response": "local reply", "logprobs": None}

        prep = _make_prep(route=RouteType.LOCAL)
        trace = MagicMock()
        trace.to_dict.return_value = {}
        from core.cognition.pipeline.dispatch import dispatch_blocking
        dispatch_blocking(prep, trace=trace)

        mock_gen_local.assert_called_once()
        _, kwargs = mock_gen_local.call_args
        assert kwargs["temperature"] == 0.3
        assert kwargs["num_predict"] == 1024


class TestDispatchStreamingParams:
    """Verify resolved generation params reach the provider router in streaming dispatch."""

    @patch("core.cognition.pipeline.dispatch.log_interaction_complete")
    @patch("core.cognition.pipeline.dispatch.log_routing_decision")
    @patch("core.cognition.pipeline.dispatch.post_process", return_value=_POST)
    @patch("core.cognition.pipeline.dispatch.get_provider_router")
    @patch("core.rooms.manager.get_room_manager")
    @patch("core.cognition.pipeline.dispatch.get_setting", side_effect=_dispatch_settings)
    def test_room_temperature_flows_to_stream_provider(
        self, mock_settings, mock_rm, mock_router_fn, mock_pp, mock_log_route, mock_log_int,
    ):
        room = _mock_room(temperature=0.9, max_tokens=None)
        room.allowed_providers = None
        room.model.model = None
        room.model.provider = "anthropic"
        mock_rm.return_value.get_active_room.return_value = room

        def _settings_with_provider(key):
            if key == "provider_default":
                return "anthropic"
            return _dispatch_settings(key)
        mock_settings.side_effect = _settings_with_provider

        router = MagicMock()
        router.route_stream.return_value = iter(["hello", " world"])
        router.last_routed_provider = "anthropic"
        mock_router_fn.return_value = router

        prep = _make_prep(route=RouteType.CLOUD)
        trace = MagicMock()
        trace.to_dict.return_value = {}
        from core.cognition.pipeline.dispatch import dispatch_streaming
        # Consume the generator
        chunks = list(dispatch_streaming(prep, trace=trace))

        _, kwargs = router.route_stream.call_args
        assert kwargs["temperature"] == 0.9
        assert kwargs["max_tokens"] == 2048


class TestTraceRoomParams:
    """Routing trace includes room_temperature/room_max_tokens when overrides active."""

    def test_trace_includes_room_params(self):
        """Room override → trace has room_temperature."""
        from core.cognition.pipeline.trace import RoutingTrace

        trace = RoutingTrace(provider="ollama", model="qwen2.5:14b")
        trace.room_temperature = 0.9
        trace.room_max_tokens = 4096

        d = trace.to_dict()
        assert d["room_temperature"] == 0.9
        assert d["room_max_tokens"] == 4096

    def test_trace_omits_room_when_default(self):
        """No Room override → trace lacks room_temperature."""
        from core.cognition.pipeline.trace import RoutingTrace

        trace = RoutingTrace(provider="ollama", model="qwen2.5:14b")

        d = trace.to_dict()
        assert "room_temperature" not in d
        assert "room_max_tokens" not in d


# ---------------------------------------------------------------------------
# CLI tests: bare `room` display + `room edit --temperature/--max-tokens`
# ---------------------------------------------------------------------------

from click.testing import CliRunner
from core.interface.cli import main


@pytest.fixture()
def isolated_rooms(tmp_path, monkeypatch):
    from core.rooms.manager import reset_room_manager
    reset_room_manager()
    monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
    yield
    reset_room_manager()


@pytest.fixture()
def runner():
    return CliRunner()


class TestCLIRoomGenParams:
    """CLI shows and edits per-Room generation params."""

    def test_bare_room_shows_temperature(self, runner, isolated_rooms):
        """Bare `oikos room` shows per-Room temperature with global comparison."""
        # Create a room with temperature override
        result = runner.invoke(main, ["room", "create", "writing", "--name", "Writing"])
        assert result.exit_code == 0

        # Edit to set temperature
        result = runner.invoke(main, ["room", "edit", "writing", "--temperature", "0.9"])
        assert result.exit_code == 0

        # Switch to the room so it's active
        result = runner.invoke(main, ["room", "switch", "writing"])
        assert result.exit_code == 0

        # Now bare room command should show temperature
        result = runner.invoke(main, ["room"])
        assert result.exit_code == 0
        assert "0.9" in result.output
        assert "Temperature" in result.output

    def test_bare_room_shows_default_when_no_override(self, runner, isolated_rooms):
        """Bare `oikos room` shows default hint when Room has no override."""
        result = runner.invoke(main, ["room"])
        assert result.exit_code == 0
        assert "default" in result.output
        assert "Temperature" in result.output

    def test_room_edit_temperature(self, runner, isolated_rooms):
        """Edit Room temp via --temperature flag."""
        runner.invoke(main, ["room", "create", "dev", "--name", "Dev"])
        result = runner.invoke(main, ["room", "edit", "dev", "--temperature", "0.5"])
        assert result.exit_code == 0
        assert "updated" in result.output.lower()

        # Verify via show
        result = runner.invoke(main, ["room", "show", "dev"])
        assert "0.5" in result.output

    def test_room_edit_max_tokens(self, runner, isolated_rooms):
        """Edit Room max_tokens via --max-tokens flag."""
        runner.invoke(main, ["room", "create", "dev2", "--name", "Dev2"])
        result = runner.invoke(main, ["room", "edit", "dev2", "--max-tokens", "4096"])
        assert result.exit_code == 0

        result = runner.invoke(main, ["room", "show", "dev2"])
        assert "4096" in result.output

    def test_room_edit_temperature_validation(self, runner, isolated_rooms):
        """Temperature outside 0.0-2.0 is rejected."""
        runner.invoke(main, ["room", "create", "val", "--name", "Val"])
        result = runner.invoke(main, ["room", "edit", "val", "--temperature", "3.0"])
        assert result.exit_code != 0

    def test_room_edit_max_tokens_validation(self, runner, isolated_rooms):
        """Max tokens outside 256-32768 is rejected."""
        runner.invoke(main, ["room", "create", "val2", "--name", "Val2"])
        result = runner.invoke(main, ["room", "edit", "val2", "--max-tokens", "100"])
        assert result.exit_code != 0
