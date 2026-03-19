"""End-to-end integration tests for the oikOS Agent Framework middleware chain."""

import asyncio
import json
import pytest
from unittest.mock import MagicMock, patch

from core.framework.decorator import oikos_tool, clear_registry, PrivacyTier, AutonomyLevel
from core.framework.server import OikosServer
from core.framework.middleware.auth import AuthMiddleware
from core.framework.middleware.privacy import PrivacyMiddleware
from core.framework.middleware.autonomy import AutonomyMiddleware
from core.framework.middleware.rate_limit import RateLimitMiddleware
from core.framework.middleware.audit import AuditMiddleware
from core.framework.exceptions import ApprovalRequired, RateLimitExceeded, PrivacyViolation
from core.interface.models import ActionClass


@pytest.fixture(autouse=True)
def clean():
    clear_registry()
    yield
    clear_registry()


def _build_server(tmp_path, middleware=None):
    """Build a server with audit logging to tmp_path."""
    if middleware is None:
        classifier = MagicMock()
        classifier.classify.return_value = PrivacyTier.SAFE
        middleware = [
            PrivacyMiddleware(classifier),
            AutonomyMiddleware(),
            RateLimitMiddleware(),
            AuditMiddleware(),
        ]
    server = OikosServer(name="test", middleware=middleware)
    return server


class TestFullChain:
    def test_safe_tool_through_all_layers(self, tmp_path):
        @oikos_tool(name="greet", description="Greets", autonomy=AutonomyLevel.SAFE, rate_limit=0)
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        audit_file = tmp_path / "agency" / "tool_audit.jsonl"
        server = _build_server(tmp_path)
        server.register_tools()

        wrapper = server._build_wrapper(greet, greet._oikos_meta)
        with patch("core.framework.middleware.audit.AUDIT_LOG_DIR", tmp_path / "agency"), \
             patch("core.framework.middleware.audit.AUDIT_LOG_FILE", audit_file):
            result = asyncio.get_event_loop().run_until_complete(wrapper(name="World"))

        assert result == "Hello, World!"
        assert audit_file.exists()
        record = json.loads(audit_file.read_text().strip())
        assert record["tool_name"] == "greet"
        assert record["error"] is None

    def test_ask_first_raises_approval_required(self):
        queue = MagicMock()
        proposal = MagicMock()
        proposal.proposal_id = "prop-abc"
        queue.propose.return_value = proposal

        @oikos_tool(name="dangerous", description="Dangerous", autonomy=AutonomyLevel.ASK_FIRST)
        def dangerous() -> str:
            return "executed"

        classifier = MagicMock()
        classifier.classify.return_value = PrivacyTier.SAFE
        middleware = [
            PrivacyMiddleware(classifier),
            AutonomyMiddleware(queue=queue),
        ]
        server = OikosServer(name="test", middleware=middleware)
        server.register_tools()

        wrapper = server._build_wrapper(dangerous, dangerous._oikos_meta)
        with pytest.raises(ApprovalRequired) as exc:
            asyncio.get_event_loop().run_until_complete(wrapper())
        assert exc.value.proposal_id == "prop-abc"

    def test_prohibited_blocked(self):
        @oikos_tool(name="banned", description="Banned", autonomy=AutonomyLevel.PROHIBITED)
        def banned() -> str:
            return "should not execute"

        classifier = MagicMock()
        classifier.classify.return_value = PrivacyTier.SAFE
        server = OikosServer(
            name="test",
            middleware=[PrivacyMiddleware(classifier), AutonomyMiddleware()],
        )
        server.register_tools()

        wrapper = server._build_wrapper(banned, banned._oikos_meta)
        with pytest.raises(PermissionError, match="PROHIBITED"):
            asyncio.get_event_loop().run_until_complete(wrapper())

    def test_rate_limit_fires_mid_chain(self):
        @oikos_tool(name="limited", description="Limited", rate_limit=2)
        def limited() -> str:
            return "ok"

        classifier = MagicMock()
        classifier.classify.return_value = PrivacyTier.SAFE
        server = OikosServer(
            name="test",
            middleware=[PrivacyMiddleware(classifier), RateLimitMiddleware()],
        )
        server.register_tools()
        wrapper = server._build_wrapper(limited, limited._oikos_meta)

        # First 2 calls pass
        for _ in range(2):
            asyncio.get_event_loop().run_until_complete(wrapper())

        # Third call hits rate limit
        with pytest.raises(RateLimitExceeded):
            asyncio.get_event_loop().run_until_complete(wrapper())

    def test_audit_runs_even_on_error(self, tmp_path):
        @oikos_tool(name="crasher", description="Crashes")
        def crasher() -> str:
            raise ValueError("boom")

        audit_file = tmp_path / "agency" / "tool_audit.jsonl"
        classifier = MagicMock()
        classifier.classify.return_value = PrivacyTier.SAFE
        server = OikosServer(
            name="test",
            middleware=[PrivacyMiddleware(classifier), AuditMiddleware()],
        )
        server.register_tools()
        wrapper = server._build_wrapper(crasher, crasher._oikos_meta)

        with patch("core.framework.middleware.audit.AUDIT_LOG_DIR", tmp_path / "agency"), \
             patch("core.framework.middleware.audit.AUDIT_LOG_FILE", audit_file):
            with pytest.raises(ValueError, match="boom"):
                asyncio.get_event_loop().run_until_complete(wrapper())

        assert audit_file.exists()
        record = json.loads(audit_file.read_text().strip())
        assert "ValueError: boom" in record["error"]

    def test_ask_first_returns_approval_prompt_with_error_handler(self):
        """When ErrorHandler is in chain, ASK_FIRST returns a descriptive dict, not an error."""
        queue = MagicMock()
        proposal = MagicMock()
        proposal.proposal_id = "prop-xyz"
        queue.propose.return_value = proposal

        @oikos_tool(name="needs_approval", description="Needs approval", autonomy=AutonomyLevel.ASK_FIRST)
        def needs_approval(path: str) -> str:
            return "executed"

        from core.framework.middleware.error_handler import ErrorHandlerMiddleware
        classifier = MagicMock()
        classifier.classify.return_value = PrivacyTier.SAFE
        middleware = [
            ErrorHandlerMiddleware(),
            PrivacyMiddleware(classifier),
            AutonomyMiddleware(queue=queue),
        ]
        server = OikosServer(name="test", middleware=middleware)
        server.register_tools()

        wrapper = server._build_wrapper(needs_approval, needs_approval._oikos_meta)
        result = asyncio.get_event_loop().run_until_complete(wrapper(path="/some/file"))
        assert result["status"] == "approval_required"
        assert result["proposal_id"] == "prop-xyz"
        assert "needs_approval" in result["message"]
        assert "/some/file" in result["message"]

    def test_direct_call_bypasses_mcp(self):
        @oikos_tool(name="direct", description="Direct")
        def direct(x: int) -> int:
            return x + 1

        # Call directly — no MCP, no middleware
        assert direct(5) == 6
