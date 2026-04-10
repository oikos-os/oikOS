"""Transport helpers for the oikOS Agent Framework."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MCP_HTTP_PORT = 8421


def run_server(
    transport: str = "stdio",
    toolsets: list[str] | None = None,
    http_port: int = MCP_HTTP_PORT,
) -> None:
    """Convenience entry point for starting the oikOS MCP server.

    Args:
        transport: "stdio" for Claude Desktop, "streamable-http" for network.
        toolsets: Only expose tools in these toolsets (None = all).
        http_port: Port for HTTP transport.
    """
    from core.framework.server import OikosServer

    kwargs = {}
    if transport in ("streamable-http", "http"):
        kwargs["host"] = "127.0.0.1"
        kwargs["port"] = http_port

    server = OikosServer(name="oikos", **kwargs)

    if toolsets:
        for ts in toolsets:
            server.register_tools(toolset=ts)
    else:
        server.register_tools()

    log.info("Starting oikOS MCP server (transport=%s)", transport)
    server.run(transport=transport if transport != "http" else "streamable-http")
