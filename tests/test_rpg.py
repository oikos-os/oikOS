"""Tests for Module 7 — RPG overlay: stats, XP, achievements, persistence."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest


# ── XP and Leveling ──────────────────────────────────────────────────

class TestXPSystem:
    def test_xp_for_level_progression(self):
        from core.agency.rpg import xp_for_level

        assert xp_for_level(1) == 0
        assert xp_for_level(2) == 150
        assert xp_for_level(3) > xp_for_level(2)

    def test_level_from_xp(self):
        from core.agency.rpg import level_from_xp

        assert level_from_xp(0) == 1
        assert level_from_xp(149) == 1
        assert level_from_xp(150) == 2
        assert level_from_xp(10000) >= 5

    def test_grant_xp_increments(self, tmp_path):
        from core.agency.rpg import grant_xp, _default_state

        stats_file = tmp_path / "stats.json"
        with patch("core.agency.rpg.RPG_STATS_FILE", stats_file), \
             patch("core.agency.rpg.RPG_DIR", tmp_path):
            state = _default_state()
            state = grant_xp("test_pass", state)
            assert state["total_xp"] == 10
            assert state["counters"]["tests_passed"] == 1

            state = grant_xp("gauntlet_pass", state)
            assert state["total_xp"] == 60
            assert state["counters"]["gauntlet_runs"] == 1

    def test_grant_xp_unknown_event(self, tmp_path):
        from core.agency.rpg import grant_xp, _default_state

        stats_file = tmp_path / "stats.json"
        with patch("core.agency.rpg.RPG_STATS_FILE", stats_file), \
             patch("core.agency.rpg.RPG_DIR", tmp_path):
            state = _default_state()
            state = grant_xp("nonexistent_event", state)
            assert state["total_xp"] == 0


# ── Achievements ─────────────────────────────────────────────────────

class TestAchievements:
    def test_first_blood_unlocks_on_gauntlet(self, tmp_path):
        from core.agency.rpg import grant_xp, _default_state

        stats_file = tmp_path / "stats.json"
        with patch("core.agency.rpg.RPG_STATS_FILE", stats_file), \
             patch("core.agency.rpg.RPG_DIR", tmp_path):
            state = _default_state()
            state = grant_xp("gauntlet_pass", state)
            assert "first_blood" in state["achievements_unlocked"]

    def test_manual_unlock(self, tmp_path):
        from core.agency.rpg import unlock_achievement, _default_state

        stats_file = tmp_path / "stats.json"
        with patch("core.agency.rpg.RPG_STATS_FILE", stats_file), \
             patch("core.agency.rpg.RPG_DIR", tmp_path):
            state = _default_state()
            stats_file.write_text(json.dumps(state))
            state = unlock_achievement("iron_spine")
            assert "iron_spine" in state["achievements_unlocked"]

    def test_duplicate_unlock_ignored(self, tmp_path):
        from core.agency.rpg import unlock_achievement, _default_state

        stats_file = tmp_path / "stats.json"
        with patch("core.agency.rpg.RPG_STATS_FILE", stats_file), \
             patch("core.agency.rpg.RPG_DIR", tmp_path):
            state = _default_state()
            state["achievements_unlocked"] = ["iron_spine"]
            stats_file.write_text(json.dumps(state))
            state = unlock_achievement("iron_spine")
            assert state["achievements_unlocked"].count("iron_spine") == 1


# ── Stat Calculation ─────────────────────────────────────────────────

class TestStatCalculation:
    def test_stats_from_counters(self, tmp_path):
        from core.agency.rpg import calculate_stats, _default_state

        stats_file = tmp_path / "stats.json"
        with patch("core.agency.rpg.RPG_STATS_FILE", stats_file), \
             patch("core.agency.rpg.RPG_DIR", tmp_path):
            state = _default_state()
            state["counters"]["tests_passed"] = 500
            state["counters"]["gauntlet_perfect_streak"] = 5
            state["counters"]["vault_promotions"] = 30
            state["total_xp"] = 5000
            stats_file.write_text(json.dumps(state))

            result = calculate_stats()
            assert result["stats"]["intelligence"] == 50  # 500/10
            assert result["stats"]["defense"] == 100  # 5*20, capped
            assert result["stats"]["memory"] == 60  # 30*2
            assert result["level"] >= 1
            assert "xp_pct" in result

    def test_stats_capped_at_100(self, tmp_path):
        from core.agency.rpg import calculate_stats, _default_state

        stats_file = tmp_path / "stats.json"
        with patch("core.agency.rpg.RPG_STATS_FILE", stats_file), \
             patch("core.agency.rpg.RPG_DIR", tmp_path):
            state = _default_state()
            state["counters"]["tests_passed"] = 9999
            stats_file.write_text(json.dumps(state))

            result = calculate_stats()
            assert result["stats"]["intelligence"] == 100


# ── Persistence ──────────────────────────────────────────────────────

class TestPersistence:
    def test_roundtrip(self, tmp_path):
        from core.agency.rpg import load_rpg_state, save_rpg_state, _default_state

        stats_file = tmp_path / "stats.json"
        with patch("core.agency.rpg.RPG_STATS_FILE", stats_file), \
             patch("core.agency.rpg.RPG_DIR", tmp_path):
            state = _default_state()
            state["total_xp"] = 1234
            save_rpg_state(state)

            loaded = load_rpg_state()
            assert loaded["total_xp"] == 1234

    def test_load_missing_file(self, tmp_path):
        from core.agency.rpg import load_rpg_state

        stats_file = tmp_path / "nonexistent.json"
        with patch("core.agency.rpg.RPG_STATS_FILE", stats_file):
            state = load_rpg_state()
            assert state["total_xp"] == 0
            assert state["level"] == 1


# ── API Endpoints ────────────────────────────────────────────────────

class TestRPGApi:
    @patch("core.agency.rpg.RPG_STATS_FILE")
    def test_get_rpg_stats(self, mock_file):
        from fastapi.testclient import TestClient
        from core.interface.api.server import create_app
        from core.agency.rpg import _default_state

        mock_file.exists.return_value = False

        client = TestClient(create_app())
        r = client.get("/api/rpg/stats")
        assert r.status_code == 200
        assert "level" in r.json()
        assert "stats" in r.json()
        assert "achievements_all" in r.json()

    @patch("core.agency.rpg.save_rpg_state")
    @patch("core.agency.rpg.load_rpg_state")
    def test_post_rpg_xp(self, mock_load, mock_save):
        from fastapi.testclient import TestClient
        from core.interface.api.server import create_app
        from core.agency.rpg import _default_state

        mock_load.return_value = _default_state()

        client = TestClient(create_app())
        r = client.post("/api/rpg/xp", json={"event_type": "test_pass"})
        assert r.status_code == 200
        assert r.json()["granted"] == 10

    @patch("core.agency.rpg.save_rpg_state")
    @patch("core.agency.rpg.load_rpg_state")
    def test_post_rpg_xp_unknown(self, mock_load, mock_save):
        from fastapi.testclient import TestClient
        from core.interface.api.server import create_app
        from core.agency.rpg import _default_state

        mock_load.return_value = _default_state()

        client = TestClient(create_app())
        r = client.post("/api/rpg/xp", json={"event_type": "fake"})
        assert r.status_code == 200
        assert r.json()["granted"] == 0
