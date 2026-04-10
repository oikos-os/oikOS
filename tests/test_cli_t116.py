"""Surface tests for T-116 routing badge — API + CLI."""

import json
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient


def test_api_response_includes_trace():
    """SSE done payload includes routing_trace dict."""
    from core.interface.api.server import create_app
    app = create_app(dev=True)
    client = TestClient(app)

    mock_resp = MagicMock()
    mock_resp.text = "Hello"
    mock_resp.route = MagicMock(value="local")
    mock_resp.model_used = "qwen2.5:14b"
    mock_resp.confidence = 85.0
    mock_resp.pii_scrubbed = False
    mock_resp.routing_decision = None
    mock_resp.contradiction = None
    mock_resp.routing_trace = {
        "badge": "ollama/qwen2.5:14b · simple query",
        "provider": "ollama/qwen2.5:14b",
        "model": "qwen2.5:14b",
        "routing_reason": "simple query",
        "content_class": "SAFE",
        "complexity": "SIMPLE",
        "pii_anonymized": False,
        "output_filtered": False,
        "cosine_gate_fired": False,
        "never_leave_fired": False,
        "room_restricted": False,
        "confidence_escalated": False,
    }

    def mock_stream(*args, **kwargs):
        yield {"delta": "Hello", "done": False, "response": None}
        yield {"delta": "", "done": True, "response": mock_resp}

    with patch("core.cognition.handler.execute_query_stream", side_effect=mock_stream):
        response = client.post("/api/chat", json={"query": "test"})

    lines = [l for l in response.text.strip().split("\n") if l.startswith("data: ")]
    last_data = json.loads(lines[-1].replace("data: ", ""))
    assert last_data["done"] is True
    assert "routing_trace" in last_data
    assert last_data["routing_trace"]["provider"] == "ollama/qwen2.5:14b"


def test_sse_stream_trace_after_deltas():
    """routing_trace only appears in the done event, not in delta events."""
    from core.interface.api.server import create_app
    app = create_app(dev=True)
    client = TestClient(app)

    mock_resp = MagicMock()
    mock_resp.text = "Hi"
    mock_resp.route = MagicMock(value="local")
    mock_resp.model_used = "qwen2.5:14b"
    mock_resp.confidence = 80.0
    mock_resp.pii_scrubbed = False
    mock_resp.routing_decision = None
    mock_resp.contradiction = None
    mock_resp.routing_trace = {"badge": "ollama · simple query", "provider": "ollama", "model": "qwen2.5:14b"}

    def mock_stream(*args, **kwargs):
        yield {"delta": "Hi", "done": False, "response": None}
        yield {"delta": "", "done": True, "response": mock_resp}

    with patch("core.cognition.handler.execute_query_stream", side_effect=mock_stream):
        response = client.post("/api/chat", json={"query": "test"})

    lines = [l for l in response.text.strip().split("\n") if l.startswith("data: ")]
    delta_data = json.loads(lines[0].replace("data: ", ""))
    assert "routing_trace" not in delta_data


def test_cli_query_prints_badge():
    """oikos query output includes routing badge line."""
    import re
    from click.testing import CliRunner
    from core.interface.cli import main

    mock_resp = MagicMock()
    mock_resp.text = "Hello world"
    mock_resp.route = MagicMock(value="local")
    mock_resp.model_used = "qwen2.5:14b"
    mock_resp.confidence = 85.0
    mock_resp.pii_scrubbed = False
    mock_resp.routing_decision = MagicMock(reason="auto")
    mock_resp.contradiction = None
    mock_resp.routing_trace = {
        "badge": "ollama/qwen2.5:14b · simple query",
        "provider": "ollama/qwen2.5:14b",
        "model": "qwen2.5:14b",
        "routing_reason": "simple query",
    }

    with patch("core.cognition.handler.execute_query", return_value=mock_resp):
        runner = CliRunner()
        result = runner.invoke(main, ["query", "hello", "--no-stream", "-y"])

    # Strip ANSI escape codes before asserting — Rich highlights version strings
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "ollama/qwen2.5:14b" in plain
    assert "simple query" in plain
