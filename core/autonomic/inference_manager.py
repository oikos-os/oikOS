"""LocalInferenceManager — provider-aware local inference lifecycle.

Protocol for backend-agnostic management. OllamaManager is the first
(and currently only) implementation.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import subprocess
import sys
from pathlib import Path
from typing import Protocol

import httpx

from core.cognition.providers.config_loader import PROVIDERS_TOML_PATH, load_providers_config
from core.rooms.manager import get_room_manager

log = logging.getLogger(__name__)

OLLAMA_STOP_FILE = Path("D:/COMMAND/flags/ollama_stopped")
OLLAMA_BASE_URL = "http://localhost:11434"


def _find_ollama_pid() -> int | None:
    """Find running ollama.exe PID via Windows API. Returns None if not running."""
    if sys.platform != "win32":
        return None
    try:
        TH32CS_SNAPPROCESS = 0x00000002

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.wintypes.DWORD),
                ("cntUsage", ctypes.wintypes.DWORD),
                ("th32ProcessID", ctypes.wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", ctypes.wintypes.DWORD),
                ("cntThreads", ctypes.wintypes.DWORD),
                ("th32ParentProcessID", ctypes.wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == ctypes.c_void_p(-1).value:
            return None

        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(pe)

        try:
            if not kernel32.Process32First(snap, ctypes.byref(pe)):
                return None
            while True:
                name = pe.szExeFile.decode("utf-8", errors="ignore").lower()
                if name == "ollama.exe":
                    return pe.th32ProcessID
                if not kernel32.Process32Next(snap, ctypes.byref(pe)):
                    break
        finally:
            kernel32.CloseHandle(snap)
    except Exception:
        pass
    return None


def _terminate_process(pid: int) -> None:
    """Terminate a Windows process by PID."""
    if sys.platform != "win32":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
        if handle:
            kernel32.TerminateProcess(handle, 1)
            kernel32.CloseHandle(handle)
    except Exception:
        pass


class LocalInferenceManager(Protocol):
    """Backend-agnostic local inference lifecycle manager."""

    def should_run(self) -> bool: ...
    async def start(self) -> bool: ...
    async def stop(self) -> bool: ...
    async def health_check(self) -> bool: ...
    async def restart(self) -> bool: ...
    def is_intentional_stop(self) -> bool: ...
    def backend_name(self) -> str: ...
    def reload_config(self) -> None: ...


class OllamaManager:
    """Manages Ollama process lifecycle based on providers.toml + Room configs."""

    def __init__(self, stop_file: Path | None = None):
        self._stop_file = stop_file or OLLAMA_STOP_FILE
        self._ollama_needed: bool = False
        self._config_mtime: float = 0.0

    def check_config_changed(self, path: Path | None = None) -> bool:
        """Check if providers.toml mtime has changed since last reload."""
        p = path or PROVIDERS_TOML_PATH
        try:
            mtime = p.stat().st_mtime
            return mtime != self._config_mtime
        except OSError:
            return False

    def reload_config(self) -> None:
        """Re-read providers.toml + Room configs. Update _ollama_needed."""
        try:
            config = load_providers_config()
        except Exception:
            log.warning("Failed to load providers.toml — assuming Ollama not needed")
            self._ollama_needed = False
            return

        try:
            self._config_mtime = PROVIDERS_TOML_PATH.stat().st_mtime
        except OSError:
            pass

        providers = config.get("providers", {})

        # Collect enabled Ollama provider names
        ollama_provider_names = {
            name
            for name, prov in providers.items()
            if prov.get("type") == "ollama" and prov.get("enabled", True) is not False
        }

        if not ollama_provider_names:
            self._ollama_needed = False
            return

        # Check 1: global default is an Ollama provider
        default_name = config.get("general", {}).get("default", "local")
        if default_name in ollama_provider_names:
            self._ollama_needed = True
            return

        # Check 2: any Room's allowed_providers references an Ollama provider
        try:
            rm = get_room_manager()
            for room in rm.list_rooms():
                if room.allowed_providers:
                    for p in room.allowed_providers:
                        if p in ollama_provider_names:
                            self._ollama_needed = True
                            return
        except Exception:
            log.debug("Room manager unavailable — checking global config only")

        # Check 3: cloud_fallback points to an Ollama provider
        fallback = config.get("general", {}).get("fallback")
        if fallback in ollama_provider_names:
            self._ollama_needed = True
            return

        self._ollama_needed = False

    def should_run(self) -> bool:
        return self._ollama_needed

    def is_intentional_stop(self) -> bool:
        return self._stop_file.exists()

    def backend_name(self) -> str:
        return "Ollama"

    async def health_check(self) -> bool:
        """Ping Ollama API. Returns True if healthy."""
        try:
            resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def start(self) -> bool:
        """Start ollama serve as a background process. Wait up to 10s for health."""
        if await self.health_check():
            self._stop_file.unlink(missing_ok=True)
            return True
        flags = {}
        if sys.platform == "win32":
            flags["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **flags,
        )
        for _ in range(10):
            await asyncio.sleep(1)
            if await self.health_check():
                self._stop_file.unlink(missing_ok=True)
                log.info("Ollama started successfully")
                return True
        log.warning("Ollama started but health check not passing after 10s")
        return False

    async def stop(self) -> bool:
        """Terminate Ollama process and write stop-file."""
        pid = _find_ollama_pid()
        if pid:
            _terminate_process(pid)
            log.info("Ollama process %d terminated", pid)
        self._stop_file.parent.mkdir(parents=True, exist_ok=True)
        self._stop_file.write_text("stopped", encoding="utf-8")
        return True

    async def restart(self) -> bool:
        """Stop then start."""
        await self.stop()
        return await self.start()
