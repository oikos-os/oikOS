"""Tests for API key authentication."""

import os
import pytest
from unittest.mock import patch

from fastapi import HTTPException

from core.interface.api.auth import get_api_key, validate_ws_token


class TestGetApiKey:
    def test_no_env_var_skips_auth(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OIKOS_API_KEY", None)
            result = get_api_key(api_key=None)
            assert result is None

    def test_valid_key_passes(self):
        with patch.dict(os.environ, {"OIKOS_API_KEY": "test-secret"}):
            result = get_api_key(api_key="test-secret")
            assert result == "test-secret"

    def test_invalid_key_raises_401(self):
        with patch.dict(os.environ, {"OIKOS_API_KEY": "test-secret"}):
            with pytest.raises(HTTPException) as exc:
                get_api_key(api_key="wrong-key")
            assert exc.value.status_code == 401

    def test_missing_key_raises_401(self):
        with patch.dict(os.environ, {"OIKOS_API_KEY": "test-secret"}):
            with pytest.raises(HTTPException) as exc:
                get_api_key(api_key=None)
            assert exc.value.status_code == 401


class TestValidateWsToken:
    def test_no_env_var_always_valid(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OIKOS_API_KEY", None)
            assert validate_ws_token(None) is True
            assert validate_ws_token("anything") is True

    def test_valid_token(self):
        with patch.dict(os.environ, {"OIKOS_API_KEY": "ws-secret"}):
            assert validate_ws_token("ws-secret") is True

    def test_invalid_token(self):
        with patch.dict(os.environ, {"OIKOS_API_KEY": "ws-secret"}):
            assert validate_ws_token("wrong") is False

    def test_missing_token(self):
        with patch.dict(os.environ, {"OIKOS_API_KEY": "ws-secret"}):
            assert validate_ws_token(None) is False
