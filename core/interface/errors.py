"""oikOS branded error messages — zero-friction actionable guidance."""

from __future__ import annotations

from collections import defaultdict

from rich import box
from rich.console import Console
from rich.panel import Panel

ERROR_MESSAGES: dict[str, tuple[str, ...]] = {
    "no_backend": (
        "\u25c8 No inference backend detected.",
        "oikOS scanned 6 ports and found nothing listening.",
        "Install Ollama, LM Studio, or any OpenAI-compatible backend.",
        "Then run: oikos serve",
    ),
    "model_not_found": (
        "\u25c8 Model not available.",
        "The requested model is not installed on your backend.",
        "Run: ollama pull {model_name}",
    ),
    "vault_empty": (
        "\u2302 Your vault is empty.",
        "oikOS needs knowledge to be useful.",
        "Add markdown files to vault/knowledge/ or use the onboarding wizard.",
    ),
    "port_in_use": (
        "\u25c8 Port {port} is already in use.",
        "Another instance of oikOS may be running.",
        "Stop it with Ctrl+C, or use: oikos serve --port {alt_port}",
    ),
    "docker_not_running": (
        "\u25c8 Docker is not running.",
        "oikOS uses Docker for containerized deployment.",
        "Start Docker Desktop, then try again.",
    ),
}


def show_error(key: str, console: Console | None = None, **kwargs: object) -> None:
    """Render a branded error panel with actionable guidance."""
    if console is None:
        from core.interface.theme import console as _console

        console = _console

    lines = ERROR_MESSAGES.get(key, ("\u25c8 An unexpected error occurred.",))
    safe_kwargs = defaultdict(lambda: "?", kwargs)
    body = "\n".join(line.format_map(safe_kwargs) for line in lines)
    console.print(Panel(body, title="\u26a0 Error", border_style="oikos.error", box=box.HEAVY, padding=(0, 2)))
