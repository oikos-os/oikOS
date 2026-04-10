"""CLI tests for oikos room commands."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from core.interface.cli import main


def _extract_json(output: str) -> dict:
    """Extract JSON object from CLI output that may have trailing usage lines."""
    # Find the end of the JSON object by matching braces
    depth = 0
    for i, ch in enumerate(output):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(output[: i + 1])
    return json.loads(output)


@pytest.fixture(autouse=True)
def isolated_rooms(tmp_path, monkeypatch):
    monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
    yield
    from core.rooms.manager import reset_room_manager

    reset_room_manager()


@pytest.fixture()
def runner():
    return CliRunner()


# ── list ─────────────────────────────────────────────────────────────


def test_room_list_shows_home(runner):
    result = runner.invoke(main, ["room", "list"])
    assert result.exit_code == 0
    assert "home" in result.output.lower()
    assert "Home" in result.output


def test_room_list_shows_active_marker(runner):
    result = runner.invoke(main, ["room", "list"])
    assert result.exit_code == 0
    assert "▸" in result.output


# ── show ─────────────────────────────────────────────────────────────


def test_room_show_home(runner):
    result = runner.invoke(main, ["room", "show", "home"])
    assert result.exit_code == 0
    data = _extract_json(result.output)
    assert data["id"] == "home"
    assert data["name"] == "Home"


def test_room_show_not_found(runner):
    result = runner.invoke(main, ["room", "show", "nonexistent"])
    assert result.exit_code != 0


# ── create ───────────────────────────────────────────────────────────


def test_room_create_basic(runner):
    result = runner.invoke(main, ["room", "create", "dev", "--name", "Dev"])
    assert result.exit_code == 0
    assert "dev" in result.output.lower()

    result = runner.invoke(main, ["room", "list"])
    assert "Dev" in result.output


def test_room_create_with_template(runner):
    result = runner.invoke(
        main, ["room", "create", "myresearch", "--name", "Research", "--template", "researcher"]
    )
    assert result.exit_code == 0

    result = runner.invoke(main, ["room", "show", "myresearch"])
    data = _extract_json(result.output)
    assert "browser" in data["toolsets"]


def test_room_create_duplicate_fails(runner):
    runner.invoke(main, ["room", "create", "dup", "--name", "Dup"])
    result = runner.invoke(main, ["room", "create", "dup", "--name", "Dup2"])
    assert result.exit_code != 0


def test_room_create_invalid_id_fails(runner):
    result = runner.invoke(main, ["room", "create", "BAD ID!", "--name", "Bad"])
    assert result.exit_code != 0


# ── switch ───────────────────────────────────────────────────────────


def test_room_switch(runner):
    runner.invoke(main, ["room", "create", "alt", "--name", "Alt"])
    result = runner.invoke(main, ["room", "switch", "alt"])
    assert result.exit_code == 0
    assert "alt" in result.output.lower()


def test_room_switch_not_found(runner):
    result = runner.invoke(main, ["room", "switch", "ghost"])
    assert result.exit_code != 0


# ── delete ───────────────────────────────────────────────────────────


def test_room_delete_requires_yes(runner):
    runner.invoke(main, ["room", "create", "tmp", "--name", "Tmp"])
    result = runner.invoke(main, ["room", "delete", "tmp"])
    assert result.exit_code == 0  # no error, just a warning
    assert "confirm" in result.output.lower() or "--yes" in result.output

    # Room still exists
    result = runner.invoke(main, ["room", "show", "tmp"])
    assert result.exit_code == 0


def test_room_delete_with_yes(runner):
    runner.invoke(main, ["room", "create", "tmp2", "--name", "Tmp2"])
    result = runner.invoke(main, ["room", "delete", "tmp2", "--yes"])
    assert result.exit_code == 0
    assert "deleted" in result.output.lower()

    result = runner.invoke(main, ["room", "show", "tmp2"])
    assert result.exit_code != 0


def test_room_delete_home_fails(runner):
    result = runner.invoke(main, ["room", "delete", "home", "--yes"])
    assert result.exit_code != 0


# ── edit ─────────────────────────────────────────────────────────────


def test_room_edit_name(runner):
    runner.invoke(main, ["room", "create", "editable", "--name", "Old"])
    result = runner.invoke(main, ["room", "edit", "editable", "--name", "New"])
    assert result.exit_code == 0

    result = runner.invoke(main, ["room", "show", "editable"])
    data = _extract_json(result.output)
    assert data["name"] == "New"


def test_room_edit_add_toolset(runner):
    runner.invoke(main, ["room", "create", "tools", "--name", "Tools", "--template", "writing"])
    result = runner.invoke(main, ["room", "edit", "tools", "--add-toolset", "browser"])
    assert result.exit_code == 0

    result = runner.invoke(main, ["room", "show", "tools"])
    data = _extract_json(result.output)
    assert "browser" in data["toolsets"]


def test_room_edit_no_changes(runner):
    runner.invoke(main, ["room", "create", "noop", "--name", "Noop"])
    result = runner.invoke(main, ["room", "edit", "noop"])
    assert result.exit_code == 0
    assert "no changes" in result.output.lower()


# ── export / import ──────────────────────────────────────────────────


def test_room_export(runner):
    runner.invoke(main, ["room", "create", "exp", "--name", "Export"])
    result = runner.invoke(main, ["room", "export", "exp"])
    assert result.exit_code == 0
    data = _extract_json(result.output)
    assert data["id"] == "exp"


def test_room_import(runner, tmp_path):
    # Use a subdirectory so the file isn't in ROOMS_DIR (which is tmp_path)
    imports_dir = tmp_path / "imports"
    imports_dir.mkdir()
    config = {
        "id": "imported",
        "name": "Imported Room",
        "description": "From file",
    }
    import_file = imports_dir / "import.json"
    import_file.write_text(json.dumps(config), encoding="utf-8")

    result = runner.invoke(main, ["room", "import", str(import_file)])
    assert result.exit_code == 0
    assert "imported" in result.output.lower()

    result = runner.invoke(main, ["room", "show", "imported"])
    data = _extract_json(result.output)
    assert data["name"] == "Imported Room"


def test_room_import_invalid_json(runner, tmp_path):
    imports_dir = tmp_path / "imports"
    imports_dir.mkdir()
    bad_file = imports_dir / "bad.json"
    bad_file.write_text("not json", encoding="utf-8")

    result = runner.invoke(main, ["room", "import", str(bad_file)])
    assert result.exit_code != 0


def test_room_list_panel_formatting(runner):
    """Room list uses Rich Panel with active marker."""
    result = runner.invoke(main, ["room", "list"])
    assert result.exit_code == 0
    assert "▸" in result.output
    assert "ROOMS" in result.output
