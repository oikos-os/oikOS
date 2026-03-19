"""RoomManager — singleton CRUD and persistence for oikOS Rooms."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from core.framework.toolsets import ALL_TOOLSETS
from core.interface.config import ROOMS_DIR
from core.rooms.defaults import home_room
from core.rooms.models import RoomConfig

log = logging.getLogger(__name__)


class RoomManager:
    """Manages Room configs on disk (JSON files) with an active-room pointer."""

    def __init__(self, rooms_dir: Path = ROOMS_DIR) -> None:
        self._dir = rooms_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._rooms: dict[str, RoomConfig] = {}
        self._ensure_home()
        self._load_rooms()

    # ── persistence ───────────────────────────────────────────────────

    def _ensure_home(self) -> None:
        home_path = self._dir / "home.json"
        if not home_path.exists():
            self._write_room(home_room())

    def _load_rooms(self) -> None:
        self._rooms.clear()
        for p in self._dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                room = RoomConfig.model_validate(data)
                self._rooms[room.id] = room
            except (json.JSONDecodeError, ValueError, OSError):
                log.warning("Failed to load room config: %s", p)

    def _write_room(self, room: RoomConfig) -> None:
        target = self._dir / f"{room.id}.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(room.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(target)

    # ── CRUD ──────────────────────────────────────────────────────────

    def list_rooms(self) -> list[RoomConfig]:
        """Return all rooms sorted: Home first, then alphabetical by name."""
        rooms = list(self._rooms.values())
        rooms.sort(key=lambda r: ("" if r.id == "home" else r.name))
        return rooms

    def get_room(self, room_id: str) -> RoomConfig:
        if room_id not in self._rooms:
            raise ValueError(f"Room '{room_id}' not found")
        return self._rooms[room_id]

    def create_room(self, config: RoomConfig) -> RoomConfig:
        self._validate_room(config)
        if config.id in self._rooms:
            raise ValueError(f"Room '{config.id}' already exists")
        self._write_room(config)
        self._rooms[config.id] = config
        return config

    def update_room(self, room_id: str, updates: dict) -> RoomConfig:
        existing = self.get_room(room_id)
        # Strip immutable fields — ID and timestamps cannot be changed via update
        for key in ("id", "created_at"):
            updates.pop(key, None)
        data = existing.model_dump()
        data.update(updates)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        updated = RoomConfig.model_validate(data)
        self._validate_room(updated)
        self._write_room(updated)
        self._rooms[room_id] = updated
        return updated

    def delete_room(self, room_id: str) -> None:
        if room_id == "home":
            raise ValueError("Cannot delete the Home room")
        if room_id not in self._rooms:
            raise ValueError(f"Room '{room_id}' not found")
        path = self._dir / f"{room_id}.json"
        if path.exists():
            path.unlink()
        del self._rooms[room_id]
        if self._read_active_id() == room_id:
            self._write_active_id("home")

    # ── active room ───────────────────────────────────────────────────

    def get_active_room(self) -> RoomConfig:
        active_id = self._read_active_id()
        if active_id not in self._rooms:
            active_id = "home"
        return self._rooms[active_id]

    def switch_room(self, room_id: str) -> RoomConfig:
        if room_id not in self._rooms:
            raise ValueError(f"Room '{room_id}' not found")
        try:
            from core.memory.session import close_session
            close_session(reason="room_switch")
        except Exception:
            pass
        self._write_active_id(room_id)
        return self._rooms[room_id]

    def _read_active_id(self) -> str:
        active_file = self._dir / ".active"
        if active_file.exists():
            return active_file.read_text(encoding="utf-8").strip()
        return "home"

    def _write_active_id(self, room_id: str) -> None:
        active_file = self._dir / ".active"
        tmp = active_file.with_suffix(".tmp")
        tmp.write_text(room_id, encoding="utf-8")
        tmp.replace(active_file)

    # ── validation ────────────────────────────────────────────────────

    def _validate_room(self, config: RoomConfig) -> None:
        if config.toolsets is not None:
            invalid = set(config.toolsets) - ALL_TOOLSETS
            if invalid:
                raise ValueError(f"Invalid toolsets: {invalid}")


# ── module-level singleton ────────────────────────────────────────────

_manager: RoomManager | None = None
_manager_lock = threading.Lock()


def get_room_manager(rooms_dir: Path | None = None) -> RoomManager:
    global _manager
    if _manager is None or rooms_dir is not None:
        with _manager_lock:
            if _manager is None or rooms_dir is not None:
                _manager = RoomManager(rooms_dir or ROOMS_DIR)
    return _manager


def reset_room_manager() -> None:
    global _manager
    _manager = None
