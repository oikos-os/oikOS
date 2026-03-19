"""Tests for audit middleware."""

import asyncio
import json
import pytest
from unittest.mock import patch

from core.framework.middleware.audit import AuditMiddleware, AUDIT_LOG_FILE
from core.framework.middleware.base import MiddlewareContext
from core.framework.decorator import OikosToolMeta


def _make_ctx(arguments=None):
    return MiddlewareContext(
        tool_name="test_tool",
        tool_meta=OikosToolMeta(name="test_tool", description="test", toolset="system"),
        arguments=arguments or {"query": "hello"},
    )


async def _noop():
    return "result"


class TestAuditMiddleware:
    def test_writes_record(self, tmp_path):
        log_dir = tmp_path / "agency"
        log_file = log_dir / "tool_audit.jsonl"
        mw = AuditMiddleware()

        with patch("core.framework.middleware.audit.AUDIT_LOG_DIR", log_dir), \
             patch("core.framework.middleware.audit.AUDIT_LOG_FILE", log_file):
            asyncio.get_event_loop().run_until_complete(mw(_make_ctx(), _noop))

        assert log_file.exists()
        record = json.loads(log_file.read_text().strip())
        assert record["tool_name"] == "test_tool"
        assert record["toolset"] == "system"
        assert "arguments_hash" in record
        assert record["error"] is None

    def test_arguments_are_hashed(self, tmp_path):
        log_dir = tmp_path / "agency"
        log_file = log_dir / "tool_audit.jsonl"
        mw = AuditMiddleware()

        with patch("core.framework.middleware.audit.AUDIT_LOG_DIR", log_dir), \
             patch("core.framework.middleware.audit.AUDIT_LOG_FILE", log_file):
            asyncio.get_event_loop().run_until_complete(mw(_make_ctx({"secret": "password123"}), _noop))

        record = json.loads(log_file.read_text().strip())
        assert "password123" not in record["arguments_hash"]
        assert len(record["arguments_hash"]) == 16  # SHA-256 truncated

    def test_result_truncated(self, tmp_path):
        log_dir = tmp_path / "agency"
        log_file = log_dir / "tool_audit.jsonl"
        mw = AuditMiddleware()

        async def long_result():
            return "x" * 500

        with patch("core.framework.middleware.audit.AUDIT_LOG_DIR", log_dir), \
             patch("core.framework.middleware.audit.AUDIT_LOG_FILE", log_file):
            asyncio.get_event_loop().run_until_complete(mw(_make_ctx(), long_result))

        record = json.loads(log_file.read_text().strip())
        assert len(record["result_preview"]) == 200

    def test_error_recorded(self, tmp_path):
        log_dir = tmp_path / "agency"
        log_file = log_dir / "tool_audit.jsonl"
        mw = AuditMiddleware()

        async def fail():
            raise ValueError("boom")

        with patch("core.framework.middleware.audit.AUDIT_LOG_DIR", log_dir), \
             patch("core.framework.middleware.audit.AUDIT_LOG_FILE", log_file):
            with pytest.raises(ValueError):
                asyncio.get_event_loop().run_until_complete(mw(_make_ctx(), fail))

        record = json.loads(log_file.read_text().strip())
        assert "ValueError: boom" in record["error"]

    def test_always_runs_on_error(self, tmp_path):
        log_dir = tmp_path / "agency"
        log_file = log_dir / "tool_audit.jsonl"
        mw = AuditMiddleware()

        async def fail():
            raise RuntimeError("crash")

        with patch("core.framework.middleware.audit.AUDIT_LOG_DIR", log_dir), \
             patch("core.framework.middleware.audit.AUDIT_LOG_FILE", log_file):
            with pytest.raises(RuntimeError):
                asyncio.get_event_loop().run_until_complete(mw(_make_ctx(), fail))

        # Audit record was still written despite the error
        assert log_file.exists()
        assert log_file.read_text().strip() != ""
