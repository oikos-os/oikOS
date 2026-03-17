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

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--transport" and i + 1 < len(args):
            transport = args[i + 1]
            i += 2
        elif args[i] == "--toolsets" and i + 1 < len(args):
            toolsets = args[i + 1].split(",")
            i += 2
        else:
            i += 1

    run_server(transport=transport, toolsets=toolsets)


if __name__ == "__main__":
    main()
