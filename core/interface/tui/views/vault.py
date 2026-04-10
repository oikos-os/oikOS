"""Vault view — file tree, markdown preview, search, and file operations."""
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import DirectoryTree, Input, Markdown, Static


def _resolve_vault_path() -> Path:
    """Find the vault/ directory, checking CWD first then relative to module."""
    cwd_vault = Path("vault")
    if cwd_vault.exists():
        return cwd_vault.resolve()
    module_vault = Path(__file__).resolve().parents[4] / "vault"
    if module_vault.exists():
        return module_vault
    return cwd_vault.resolve()


class VaultView(Widget, can_focus=True):
    """Vault screen: browse files, search, preview markdown content."""

    BINDINGS = [
        Binding("n", "new_file", "New", show=True),
        Binding("e", "edit_file", "Edit", show=True),
        Binding("d", "delete_file", "Delete", show=True),
        Binding("i", "ingest_file", "Ingest", show=True),
        Binding("escape", "clear_search", "Clear search", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._vault_path = _resolve_vault_path()
        self._selected_path: Path | None = None
        self._search_active = False

    def compose(self) -> ComposeResult:
        yield Static(
            "\u25c8 Vault \u2014 loading...",
            id="vault-header",
        )
        yield Input(placeholder="Search vault...", id="vault-search")
        with Horizontal(id="vault-content"):
            if self._vault_path.exists():
                yield DirectoryTree(str(self._vault_path), id="vault-tree")
            else:
                yield Static(
                    "vault/ directory not found",
                    id="vault-tree",
                )
            with Vertical(id="vault-preview-pane"):
                yield Markdown("*Select a file to preview*", id="file-preview")
                yield Static("", id="file-meta")

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """When a file is selected in the tree, preview it."""
        path = Path(str(event.path))
        self._selected_path = path
        self._load_preview(path)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Run vault search when Enter is pressed in the search bar."""
        if event.input.id != "vault-search":
            return
        query = event.value.strip()
        if not query:
            self._restore_tree()
            return
        self._search_active = True
        self.run_worker(self._run_search(query))

    # --- Public API ----------------------------------------------------------

    def update_header(self, file_count: int) -> None:
        """Update the vault header with file count."""
        self.query_one("#vault-header", Static).update(
            f"\u25c8 Vault \u2014 {file_count} files"
        )

    # --- Actions -------------------------------------------------------------

    def action_new_file(self) -> None:
        self.notify("Create file via vault ingest")

    def action_edit_file(self) -> None:
        if self._selected_path and self._selected_path.is_file():
            self.notify(f"Edit: {self._selected_path.name} (open in $EDITOR)")
        else:
            self.notify("No file selected", severity="warning")

    def action_delete_file(self) -> None:
        if self._selected_path and self._selected_path.is_file():
            self.notify(f"Delete {self._selected_path.name}? (not yet implemented)")
        else:
            self.notify("No file selected", severity="warning")

    def action_ingest_file(self) -> None:
        self.notify("Ingest from URL (not yet implemented)")

    def action_clear_search(self) -> None:
        if self._search_active:
            self._restore_tree()
            self.query_one("#vault-search", Input).value = ""

    # --- Internal ------------------------------------------------------------

    def _load_preview(self, path: Path) -> None:
        """Read a file and show it in the markdown preview."""
        preview = self.query_one("#file-preview", Markdown)
        meta = self.query_one("#file-meta", Static)
        # Containment check — prevent reads outside vault boundary
        try:
            path.resolve().relative_to(self._vault_path.resolve())
        except ValueError:
            preview.update("*Access denied: path outside vault*")
            meta.update("")
            return
        if not path.is_file():
            preview.update("*Not a file*")
            meta.update("")
            return
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            preview.update("*Unable to read file*")
            meta.update("")
            return

        preview.update(content)

        # Extract tier from frontmatter if present
        tier = self._extract_tier(content)
        rel = self._relative_path(path)
        parts = [f"Path: {rel}"]
        if tier:
            parts.append(f"Tier: {tier}")
        if "identity" in str(path).lower():
            parts.append("\U0001f512 Identity file")
        meta.update("  \u2502  ".join(parts))

    def _extract_tier(self, content: str) -> str:
        """Pull tier from YAML frontmatter (tier: VALUE)."""
        if not content.startswith("---"):
            return ""
        lines = content.split("\n", 20)
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if line.lower().startswith("tier:"):
                return line.split(":", 1)[1].strip()
        return ""

    def _relative_path(self, path: Path) -> str:
        """Return path relative to vault root, or just the name."""
        try:
            return str(path.relative_to(self._vault_path))
        except ValueError:
            return path.name

    async def _run_search(self, query: str) -> None:
        """Search the vault via API and display results in the preview pane."""
        try:
            client = self.app.api_client
            results = await client.search(query, limit=10)
        except Exception:
            results = []

        preview = self.query_one("#file-preview", Markdown)
        meta = self.query_one("#file-meta", Static)

        if not results:
            preview.update(f"*No results for '{query}'*")
            meta.update("")
            return

        lines = [f"## Search: {query}", f"*{len(results)} results*", ""]
        for i, r in enumerate(results, 1):
            source = r.get("source_path", "unknown")
            score = r.get("score")
            tier = r.get("tier", "")
            snippet = (r.get("content", "") or "")[:200].replace("\n", " ")
            score_str = f" ({score})" if score is not None else ""
            lines.append(f"**{i}. {source}**{score_str}")
            if tier:
                lines.append(f"  Tier: {tier}")
            lines.append(f"  {snippet}")
            lines.append("")

        preview.update("\n".join(lines))
        meta.update(f"Search results for: {query}")

    def _restore_tree(self) -> None:
        """Clear search mode and restore the tree view."""
        self._search_active = False
        self.query_one("#file-preview", Markdown).update("*Select a file to preview*")
        self.query_one("#file-meta", Static).update("")
