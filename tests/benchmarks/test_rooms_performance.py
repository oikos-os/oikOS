"""Performance benchmarks for Room vault scoping."""
import json
import time
import pytest
from unittest.mock import patch, MagicMock

from core.interface.config import PROJECT_ROOT

RESULTS_DIR = PROJECT_ROOT / "logs" / "benchmarks"


def _log_result(name: str, duration_ms: float, target_ms: float | None = None):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "benchmark": name,
        "duration_ms": round(duration_ms, 2),
        "target_ms": target_ms,
        "passed": duration_ms <= target_ms if target_ms else None,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with (RESULTS_DIR / "rooms_performance.jsonl").open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


class TestRoomPerformance:
    def test_scoped_vs_unscoped_search(self):
        """Scoped search overhead should be < 50ms additional."""
        from core.memory.search import hybrid_search

        with patch("core.memory.search.get_db") as mock_db, \
             patch("core.memory.search.embed_single", return_value=[0.1] * 768):
            mock_table = MagicMock()
            mock_db.return_value.open_table.return_value = mock_table
            mock_table.count_rows.return_value = 100
            rows = [{"chunk_id": f"c{i}", "source_path": f"knowledge/ml/doc{i}.md", "tier": "semantic",
                     "header_path": "TEST", "content": "x" * 100, "file_mtime": "2026-01-01T00:00:00Z",
                     "tags": '["ml"]', "_distance": 0.1 + i * 0.01} for i in range(100)]
            mock_table.search.return_value.vector.return_value.text.return_value.limit.return_value.rerank.return_value.to_list.return_value = rows

            t0 = time.perf_counter()
            hybrid_search("test query")
            unscoped_ms = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            hybrid_search("test query", path_filter=["knowledge/ml/"], tag_filter=["ml"])
            scoped_ms = (time.perf_counter() - t0) * 1000

        overhead = scoped_ms - unscoped_ms
        result = _log_result("scoped_search_overhead", overhead, target_ms=50.0)
        # Log but don't fail — mocked timing is not representative of real perf
        print(f"  Scoped search overhead: {overhead:.1f}ms (target: <50ms)")

    def test_room_switching_latency(self, tmp_path, monkeypatch):
        """Room switching should complete in < 200ms."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager, reset_room_manager
        from core.rooms.models import RoomConfig

        mgr = get_room_manager(tmp_path)
        mgr.create_room(RoomConfig(id="target", name="Target"))
        with patch("core.memory.session.close_session"):
            t0 = time.perf_counter()
            mgr.switch_room("target")
            duration_ms = (time.perf_counter() - t0) * 1000
        result = _log_result("room_switch", duration_ms, target_ms=200.0)
        assert result["passed"], f"Room switch {duration_ms:.1f}ms exceeds 200ms target"
        reset_room_manager()

    def test_ten_room_config_load(self, tmp_path, monkeypatch):
        """Loading 10 Room configs at startup should take < 50ms."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.models import RoomConfig
        from core.rooms.manager import RoomManager, reset_room_manager

        for i in range(10):
            room = RoomConfig(id=f"room{i}", name=f"Room {i}")
            (tmp_path / f"room{i}.json").write_text(room.model_dump_json(indent=2))
        t0 = time.perf_counter()
        mgr = RoomManager(rooms_dir=tmp_path)
        duration_ms = (time.perf_counter() - t0) * 1000
        result = _log_result("ten_room_load", duration_ms, target_ms=50.0)
        assert result["passed"], f"10-room load {duration_ms:.1f}ms exceeds 50ms target"
        assert len(mgr.list_rooms()) >= 10
        reset_room_manager()

    def test_unscoped_home_no_regression(self):
        """Home Room (no filters) baseline timing."""
        from core.memory.search import hybrid_search

        with patch("core.memory.search.get_db") as mock_db, \
             patch("core.memory.search.embed_single", return_value=[0.1] * 768):
            mock_table = MagicMock()
            mock_db.return_value.open_table.return_value = mock_table
            mock_table.count_rows.return_value = 50
            rows = [{"chunk_id": f"c{i}", "source_path": f"doc{i}.md", "tier": "semantic",
                     "header_path": "TEST", "content": "x" * 100, "file_mtime": "2026-01-01T00:00:00Z",
                     "tags": "[]", "_distance": 0.1 + i * 0.01} for i in range(50)]
            mock_table.search.return_value.vector.return_value.text.return_value.limit.return_value.rerank.return_value.to_list.return_value = rows
            t0 = time.perf_counter()
            for _ in range(10):
                hybrid_search("test query")
            avg_ms = ((time.perf_counter() - t0) * 1000) / 10
        _log_result("unscoped_home_avg", avg_ms)
        print(f"  Unscoped home avg: {avg_ms:.1f}ms")
