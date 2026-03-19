"""Tests for LiteLLMProvider — optional dependency wrapper."""

from unittest.mock import MagicMock, patch
import sys

import pytest

from core.interface.models import CompletionResponse, ProviderMessage


class TestLiteLLMProviderWithoutLib:
    def test_import_guard_no_litellm(self):
        """Provider should still import even if litellm is not installed."""
        saved = sys.modules.pop("litellm", None)
        try:
            with patch.dict(sys.modules, {"litellm": None}):
                from core.cognition.providers.litellm_provider import LiteLLMProvider
                p = LiteLLMProvider()
                assert p.is_available() is False
        finally:
            if saved:
                sys.modules["litellm"] = saved

    def test_generate_without_litellm_returns_error(self):
        saved = sys.modules.pop("litellm", None)
        try:
            with patch.dict(sys.modules, {"litellm": None}):
                from core.cognition.providers.litellm_provider import LiteLLMProvider
                p = LiteLLMProvider()
                msgs = [ProviderMessage(role="user", content="hi")]
                result = p.generate(msgs)
                assert "[INFERENCE ERROR" in result.text or "not installed" in result.text.lower()
        finally:
            if saved:
                sys.modules["litellm"] = saved


class TestLiteLLMProviderWithMockedLib:
    def test_provider_name(self):
        from core.cognition.providers.litellm_provider import LiteLLMProvider
        p = LiteLLMProvider(default_model="gpt-4o")
        assert p.provider_name == "litellm"

    def test_generate_calls_completion(self):
        mock_litellm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="LiteLLM response"))]
        mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        mock_resp.model = "gpt-4o"
        mock_litellm.completion.return_value = mock_resp

        with patch.dict(sys.modules, {"litellm": mock_litellm}):
            from core.cognition.providers.litellm_provider import LiteLLMProvider
            p = LiteLLMProvider(default_model="gpt-4o")
            p._litellm = mock_litellm
            msgs = [ProviderMessage(role="user", content="hi")]
            result = p.generate(msgs)
            assert result.text == "LiteLLM response"
            assert result.provider == "litellm"

    def test_count_tokens(self):
        from core.cognition.providers.litellm_provider import LiteLLMProvider
        p = LiteLLMProvider()
        assert p.count_tokens("one two three") == 3  # 3 * 1.3 = 3.9 → 3

    def test_satisfies_protocol(self):
        from core.cognition.providers.litellm_provider import LiteLLMProvider
        from core.cognition.providers.protocol import InferenceProvider
        p = LiteLLMProvider()
        assert isinstance(p, InferenceProvider)
