"""Audit middleware — structured JSONL logging for all tool calls."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from core.framework.middleware.base import MiddlewareContext
from core.interface.config import PROJECT_ROOT
from core.interface.models import DataTier

log = logging.getLogger(__name__)

AUDIT_LOG_DIR = PROJECT_ROOT / "logs" / "agency"
AUDIT_LOG_FILE = AUDIT_LOG_DIR / "tool_audit.jsonl"


class AuditMiddleware:
    """Logs every tool call to JSONL with hashed arguments and truncated results.

    Always runs — even on error (uses try/finally pattern).
    Arguments are SHA-256 hashed to avoid logging sensitive data.
    """

    async def __call__(self, ctx: MiddlewareContext, call_next: Callable) -> Any:
        t0 = time.monotonic()
        error_msg = None
        result = None

        try:
            result = await call_next()
            return result
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            latency_ms = int((time.monotonic() - t0) * 1000)
            self._write_record(ctx, result, error_msg, latency_ms)

    def _write_record(self, ctx: MiddlewareContext, result: Any, error: str | None, latency_ms: int) -> None:
        args_hash = hashlib.sha256(
            json.dumps(ctx.arguments, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

        # Redact result preview if content is NEVER_LEAVE
        privacy_tier = ctx.extras.get("privacy_tier")
        if privacy_tier == DataTier.NEVER_LEAVE:
            result_preview = "[REDACTED]"
        else:
            result_preview = str(result)[:200] if result is not None else None

        record = {
            "timestamp": datetime.now().isoformat(),
            "tool_name": ctx.tool_name,
            "toolset": ctx.tool_meta.toolset,
            "autonomy": ctx.tool_meta.autonomy.value if hasattr(ctx.tool_meta.autonomy, "value") else str(ctx.tool_meta.autonomy),
            "privacy": ctx.extras.get("privacy_tier", ctx.tool_meta.privacy).value if hasattr(ctx.extras.get("privacy_tier", ctx.tool_meta.privacy), "value") else "unknown",
            "client_id": ctx.client_id,
            "arguments_hash": args_hash,
            "result_preview": result_preview,
            "latency_ms": latency_ms,
            "error": error,
        }

        try:
            AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
            with AUDIT_LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except OSError as exc:
            log.warning("Failed to write audit log: %s", exc)
