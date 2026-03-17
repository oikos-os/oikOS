"""FastAPI app factory + uvicorn launcher."""

from __future__ import annotations

import logging
import threading
import time

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.interface.api.auth import get_api_key
from core.interface.config import API_VERSION

_start_time = time.monotonic()
_daemon_shutdown = threading.Event()
_daemon_thread: threading.Thread | None = None
log = logging.getLogger(__name__)


def get_uptime() -> float:
    return time.monotonic() - _start_time


def create_app(dev: bool = False) -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: launch embedded daemon thread
        global _daemon_thread
        from core.autonomic.daemon import heartbeat_tick, _init_state
        from core.interface.config import DAEMON_HEARTBEAT_INTERVAL_SEC
        from core.autonomic.events import emit_event

        _init_state()
        _daemon_shutdown.clear()

        def _daemon_loop():
            log.info("Embedded daemon thread started")
            emit_event("daemon", "embedded_start", {"mode": "serve"})
            while not _daemon_shutdown.is_set():
                try:
                    heartbeat_tick()
                except Exception as e:
                    log.error("Daemon tick error: %s: %s", type(e).__name__, e)
                _daemon_shutdown.wait(timeout=DAEMON_HEARTBEAT_INTERVAL_SEC)
            log.info("Embedded daemon thread stopped")

        _daemon_thread = threading.Thread(target=_daemon_loop, name="oikos-daemon", daemon=True)
        _daemon_thread.start()

        yield

        # Shutdown: stop daemon thread gracefully
        _daemon_shutdown.set()
        if _daemon_thread and _daemon_thread.is_alive():
            _daemon_thread.join(timeout=5)
            log.info("Daemon thread joined")

    app = FastAPI(
        title="OIKOS_OMEGA",
        version=API_VERSION,
        docs_url="/api/docs" if dev else None,
        redoc_url="/api/redoc" if dev else None,
        lifespan=lifespan,
    )

    if dev:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    from core.interface.api.routes.system import router as system_router
    from core.interface.api.routes.chat import router as chat_router
    from core.interface.api.routes.vault import router as vault_router
    from core.interface.api.routes.agents import router as agents_router
    from core.interface.api.routes.events import router as events_router
    from core.interface.api.routes.rpg import router as rpg_router
    from core.interface.api.routes.settings import router as settings_router
    from core.interface.api.routes.models import router as models_router
    from core.interface.api.routes.sessions import router as sessions_router
    from core.interface.api.routes.upload import router as upload_router
    from core.interface.api.routes.search import router as search_router
    from core.interface.api.routes.agency import router as agency_router
    from core.interface.api.ws.heartbeat import router as ws_router

    # Health endpoint is public (no auth)
    from fastapi import APIRouter
    health_router = APIRouter()

    @health_router.get("/api/health")
    def health_public():
        from core.autonomic.daemon import get_status
        from core.memory.embedder import check_health
        status = get_status()
        return {"running": status["running"], "daemon": status, "ollama_embed": check_health()}

    app.include_router(health_router)

    auth_dep = [Depends(get_api_key)]
    app.include_router(system_router, prefix="/api", dependencies=auth_dep)
    app.include_router(chat_router, prefix="/api/chat", dependencies=auth_dep)
    app.include_router(vault_router, prefix="/api/vault", dependencies=auth_dep)
    app.include_router(agents_router, prefix="/api/agents", dependencies=auth_dep)
    app.include_router(events_router, prefix="/api", dependencies=auth_dep)
    app.include_router(rpg_router, prefix="/api", dependencies=auth_dep)
    app.include_router(settings_router, prefix="/api/settings", dependencies=auth_dep)
    app.include_router(models_router, prefix="/api", dependencies=auth_dep)
    app.include_router(sessions_router, prefix="/api", dependencies=auth_dep)
    app.include_router(upload_router, prefix="/api", dependencies=auth_dep)
    app.include_router(search_router, prefix="/api", dependencies=auth_dep)
    app.include_router(agency_router, prefix="/api/agency", dependencies=auth_dep)
    app.include_router(ws_router)

    if not dev:
        from pathlib import Path
        dist = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
        if dist.exists():
            from fastapi.staticfiles import StaticFiles
            from fastapi.responses import FileResponse

            @app.get("/{full_path:path}")
            async def serve_spa(full_path: str):  # noqa: ARG001
                index = dist / "index.html"
                target = dist / full_path
                if target.is_file():
                    return FileResponse(target)
                return FileResponse(index)

    return app


# Module-level instances for uvicorn CLI usage (e.g. `uvicorn core.interface.api.server:app_dev`)
app_dev = create_app(dev=True)
app_prod = create_app(dev=False)


def run_server(port: int = 8420, dev: bool = False) -> None:
    import uvicorn

    app = app_dev if dev else app_prod
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
