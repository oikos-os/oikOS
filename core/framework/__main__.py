"""oikOS MCP Server entry point.

Usage:
    python -m core.framework                              # stdio (Claude Desktop)
    python -m core.framework --transport http              # Streamable HTTP
    python -m core.framework --toolsets vault,system       # Specific toolsets only
"""

import sys

# Register all tools before starting server
import core.framework.tools  # noqa: F401

from core.framework.transport import run_server


def main():
    transport = "stdio"
    toolsets = None
    room_id = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--transport" and i + 1 < len(args):
            transport = args[i + 1]
            i += 2
        elif args[i] == "--toolsets" and i + 1 < len(args):
            toolsets = args[i + 1].split(",")
            i += 2
        elif args[i] == "--room" and i + 1 < len(args):
            room_id = args[i + 1]
            i += 2
        else:
            i += 1

    # Room-scoped toolsets + activate room (explicit --toolsets overrides)
    if room_id:
        from core.rooms.manager import get_room_manager
        mgr = get_room_manager()
        room = mgr.get_room(room_id)
        mgr.switch_room(room_id)
        if toolsets is None and room.toolsets is not None:
            toolsets = room.toolsets

    run_server(transport=transport, toolsets=toolsets)


if __name__ == "__main__":
    main()
