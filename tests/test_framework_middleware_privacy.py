"""Tests for privacy middleware."""

import asyncio
import pytest
from unittest.mock import MagicMock

from core.framework.middleware.privacy import PrivacyMiddleware
from core.framework.middleware.base import MiddlewareContext
from core.framework.decorator import OikosToolMeta
from core.framework.exceptions import PrivacyViolation
from core.interface.models import DataTier


def _make_ctx(arguments=None, transport="stdio", privacy=DataTier.SAFE):
    return MiddlewareContext(
        tool_name="test",
        tool_meta=OikosToolMeta(name="test", description="test", privacy=privacy),
        arguments=arguments or {"query": "hello"},
        extras={"transport": transport},
    )


def _mock_classifier(tier=DataTier.SAFE):
    c = MagicMock()
    c.classify.return_value = tier
    c.anonymize.return_value = ('{"query": "[ANON]"}', {"[ANON]": "secret"})
    c.deanonymize.side_effect = lambda text, mapping: text.replace("[ANON]", "secret")
    return c


class TestInputClassification:
    def test_safe_passes_through(self):
        classifier = _mock_classifier(DataTier.SAFE)
        mw = PrivacyMiddleware(classifier)
        ctx = _make_ctx()

        async def return_result():
            return "result"

        result = asyncio.get_event_loop().run_until_complete(mw(ctx, return_result))
        assert result == "result"

    def test_never_leave_blocks_remote(self):
        classifier = _mock_classifier(DataTier.NEVER_LEAVE)
        mw = PrivacyMiddleware(classifier)
        ctx = _make_ctx(transport="http")  # remote client

        with pytest.raises(PrivacyViolation):
            asyncio.get_event_loop().run_until_complete(mw(ctx, lambda: None))

    def test_never_leave_allows_stdio(self):
        classifier = MagicMock()
        classifier.classify.side_effect = [DataTier.NEVER_LEAVE, DataTier.SAFE]
        mw = PrivacyMiddleware(classifier)
        ctx = _make_ctx(transport="stdio", privacy=DataTier.NEVER_LEAVE)

        async def return_result():
            return "local result"

        # NEVER_LEAVE on stdio is allowed (data stays local)
        result = asyncio.get_event_loop().run_until_complete(mw(ctx, return_result))
        assert result == "local result"

    def test_never_leave_blocks_remote_even_for_never_leave_tool(self):
        classifier = _mock_classifier(DataTier.NEVER_LEAVE)
        mw = PrivacyMiddleware(classifier)
        # Tool declared as NEVER_LEAVE, but remote transport — still blocked
        ctx = _make_ctx(transport="http", privacy=DataTier.NEVER_LEAVE)

        with pytest.raises(PrivacyViolation):
            asyncio.get_event_loop().run_until_complete(mw(ctx, lambda: None))

    def test_sensitive_anonymizes_input(self):
        classifier = _mock_classifier(DataTier.SENSITIVE)
        mw = PrivacyMiddleware(classifier)
        ctx = _make_ctx(arguments={"query": "secret data"})

        async def check_args():
            return "processed"

        asyncio.get_event_loop().run_until_complete(mw(ctx, check_args))
        classifier.anonymize.assert_called_once()


class TestOutputClassification:
    def test_never_leave_in_output_redacted(self):
        # Input is SAFE, but output contains NEVER_LEAVE content
        classifier = MagicMock()
        classifier.classify.side_effect = [DataTier.SAFE, DataTier.NEVER_LEAVE]
        mw = PrivacyMiddleware(classifier)
        ctx = _make_ctx()

        async def return_sensitive():
            return "arodri311 secret identity"

        result = asyncio.get_event_loop().run_until_complete(mw(ctx, return_sensitive))
        assert result == "[REDACTED: contains protected content]"

    def test_safe_output_passes(self):
        classifier = _mock_classifier(DataTier.SAFE)
        mw = PrivacyMiddleware(classifier)
        ctx = _make_ctx()

        async def return_result():
            return "clean result"

        result = asyncio.get_event_loop().run_until_complete(mw(ctx, return_result))
        assert result == "clean result"

    def test_sensitive_output_deanonymized(self):
        classifier = MagicMock()
        classifier.classify.side_effect = [DataTier.SENSITIVE, DataTier.SAFE]
        classifier.anonymize.return_value = ('{"query": "[ANON]"}', {"[ANON]": "secret"})
        classifier.deanonymize.side_effect = lambda t, m: t.replace("[ANON]", "secret")
        mw = PrivacyMiddleware(classifier)
        ctx = _make_ctx()

        async def return_anon():
            return "result with [ANON]"

        result = asyncio.get_event_loop().run_until_complete(mw(ctx, return_anon))
        assert "secret" in result

    def test_none_result_passes(self):
        classifier = _mock_classifier(DataTier.SAFE)
        mw = PrivacyMiddleware(classifier)
        ctx = _make_ctx()

        async def return_none():
            return None

        result = asyncio.get_event_loop().run_until_complete(mw(ctx, return_none))
        assert result is None
