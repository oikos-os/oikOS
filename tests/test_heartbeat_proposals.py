from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


class TestHeartbeatProposals:
    def test_heartbeat_payload_includes_pending_proposals(self):
        """Verify the heartbeat payload builder includes pending proposals."""
        from core.interface.api.ws.heartbeat import _build_heartbeat_payload

        mock_status = {"running": True, "pid": 1234}
        mock_state = MagicMock()
        mock_state.value = "idle"

        with patch("core.autonomic.daemon.get_status", return_value=mock_status), \
             patch("core.autonomic.fsm.get_current_state", return_value=mock_state), \
             patch("core.interface.api.ws.heartbeat._get_pending_proposals", return_value=[]):
            payload = _build_heartbeat_payload()
            assert "pending_proposals" in payload
            assert payload["pending_proposals"] == []

    def test_heartbeat_includes_proposal_data(self):
        from core.interface.api.ws.heartbeat import _build_heartbeat_payload

        mock_proposal = {
            "proposal_id": "abc123",
            "action_type": "write_file",
            "status": "pending",
        }
        mock_status = {"running": True}
        mock_state = MagicMock()
        mock_state.value = "idle"

        with patch("core.autonomic.daemon.get_status", return_value=mock_status), \
             patch("core.autonomic.fsm.get_current_state", return_value=mock_state), \
             patch("core.interface.api.ws.heartbeat._get_pending_proposals", return_value=[mock_proposal]):
            payload = _build_heartbeat_payload()
            assert len(payload["pending_proposals"]) == 1
            assert payload["pending_proposals"][0]["proposal_id"] == "abc123"

    def test_pending_proposals_helper_handles_missing_log(self):
        from core.interface.api.ws.heartbeat import _get_pending_proposals

        with patch("core.interface.api.ws.heartbeat.APPROVAL_PROPOSALS_LOG") as mock_path:
            mock_path.exists.return_value = False
            assert _get_pending_proposals() == []
