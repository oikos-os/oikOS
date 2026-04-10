"""OIKOS CLI — index, search, compile, query, credits, status."""

from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", message=".*doesn't match a supported version.*", module="requests")

import ctypes
import logging
import os
import re
import signal
import subprocess
import sys
import time

import click
from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from core.interface.theme import console

log = logging.getLogger(__name__)


def _toml_kv(k: str, v: object) -> str:
    """Format a single TOML key-value pair."""
    if isinstance(v, bool):
        return f"{k} = {str(v).lower()}"
    if isinstance(v, str):
        return f'{k} = "{v}"'
    return f"{k} = {v}"


class SmartGroup(click.Group):
    """Click Group that routes unknown subcommands to a default handler."""

    def resolve_command(self, ctx, args):
        if not args:
            return super().resolve_command(ctx, args)
        cmd_name = args[0]
        if cmd_name.startswith("-"):
            return super().resolve_command(ctx, args)
        if cmd_name in self.commands:
            return super().resolve_command(ctx, args)
        if "_default" in self.commands:
            return "_default", self.commands["_default"], args
        return super().resolve_command(ctx, args)


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    """oikOS — The home for AI agents."""
    if ctx.invoked_subcommand is not None:
        return

    from core.interface.snapshot import render_snapshot
    render_snapshot(console)


@main.command(name="help")
@click.pass_context
def help_cmd(ctx):
    """Show all available commands."""
    click.echo(ctx.parent.get_help())


@main.command()
def tui():
    """Launch the oikOS TUI (full-screen terminal interface)."""
    from core.interface.tui.app import run_tui_boot_splash, OikOSApp
    run_tui_boot_splash()
    OikOSApp().run()


@main.command()
@click.option("--full", is_flag=True, help="Full rebuild (drop + re-index all)")
def index(full: bool):
    """Index vault markdown files into LanceDB."""
    from core.memory.embedder import check_health

    if not check_health():
        from core.interface.errors import show_error

        show_error("no_backend")
        raise SystemExit(1)

    from core.memory.indexer import index_vault

    mode = "full rebuild" if full else "incremental"
    console.print(f"[bold]Indexing vault[/] ({mode})...")

    stats = index_vault(full_rebuild=full)

    console.print(
        f"[green]Done.[/] "
        f"files={stats['files']}  "
        f"added={stats['added']}  "
        f"skipped={stats['skipped']}  "
        f"deleted={stats['deleted']}"
    )


@main.command()
@click.argument("query")
@click.option("-n", "--limit", default=10, help="Max results")
@click.option("-t", "--tier", default=None, help="Filter by tier (core/semantic/procedural/episodic)")
def search(query: str, limit: int, tier: str | None):
    """Hybrid search across indexed vault."""
    from core.interface.models import MemoryTier
    from core.memory.search import hybrid_search

    tier_filter = MemoryTier(tier) if tier else None
    results = hybrid_search(query, limit=limit, tier_filter=tier_filter)

    if not results:
        console.print("[yellow]No results found.[/]")
        return

    table = Table(show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Score", width=6)
    table.add_column("Tier", width=10)
    table.add_column("Source", width=30)
    table.add_column("Header", width=25)
    table.add_column("Preview", width=50)

    # Highlight query terms in preview
    query_terms = [w for w in query.lower().split() if len(w) > 1]

    def _highlight(raw: str) -> Text:
        text = Text(raw)
        for term in query_terms:
            for match in re.finditer(re.escape(term), raw, re.IGNORECASE):
                text.stylize("bold reverse", match.start(), match.end())
        return text

    for i, r in enumerate(results, 1):
        preview = r.content[:120].replace("\n", " ")
        table.add_row(
            str(i),
            f"{r.final_score:.3f}",
            r.tier.value,
            r.source_path,
            r.header_path,
            _highlight(preview),
        )

    console.print(Panel(table, title=f"\u2302 Vault Search: {query!r}", box=box.ROUNDED, border_style="oikos.border"))


@main.command()
@click.argument("query")
@click.option("-b", "--budget", default=6000, help="Token budget")
@click.option("--debug", is_flag=True, help="Show per-fragment diagnostics (source, header, tokens, dedup)")
def compile(query: str, budget: int, debug: bool):
    """Compile a context window from memory tiers."""
    from core.cognition.compiler import compile_context, count_tokens, render_context

    compiled = compile_context(query, token_budget=budget)

    # Slice breakdown
    table = Table(title=f"Context: {query!r}", show_lines=True)
    table.add_column("Slice", width=12)
    table.add_column("Tokens", width=8, justify="right")
    table.add_column("Budget", width=8, justify="right")
    table.add_column("Fragments", width=10, justify="right")

    for s in compiled.slices:
        table.add_row(s.name, str(s.token_count), str(s.max_tokens), str(len(s.fragments)))

    console.print(table)
    console.print(f"\n[bold]Total:[/] {compiled.total_tokens}/{compiled.budget} tokens")

    if debug:
        console.print()
        for s in compiled.slices:
            if not s.fragments:
                continue
            console.print(f"[bold cyan]--- {s.name.upper()} ---[/]")
            for i, frag in enumerate(s.fragments):
                meta = s.fragment_meta[i] if i < len(s.fragment_meta) else None
                src = meta.source_path if meta else "?"
                hdr = meta.header_path if meta else "?"
                tok = count_tokens(frag)
                preview = frag[:80].replace("\n", " ")
                console.print(f"  [dim][{i}][/] {tok:>4}t  [green]{src}[/]")
                console.print(f"         [dim]{hdr}[/]")
                console.print(f"         {preview}...")
            console.print()
    else:
        console.print()
        rendered = render_context(compiled)
        console.print(rendered)


def _collect_feedback(resp, auto_accept: bool = False) -> None:
    """Non-blocking feedback prompt: [y] accept [n] reject [s] skip."""
    if resp.routing_decision is None:
        return

    from core.cognition.routing import backfill_user_accepted

    accepted: bool | None
    if auto_accept:
        accepted = True
        console.print("[green]Accepted (auto).[/]")
    else:
        console.print()
        console.print("[dim]Rate response:[/] [bold green]y[/]es  [bold red]n[/]o  [bold yellow]s[/]kip")

        try:
            ch = click.getchar()
        except (EOFError, KeyboardInterrupt, OSError):
            # Non-interactive or interrupted — auto-skip
            ch = "s"

        if ch in ("y", "Y"):
            accepted = True
            console.print("[green]Accepted.[/]")
        elif ch in ("n", "N"):
            accepted = False
            console.print("[red]Rejected.[/]")
        else:
            accepted = None
            console.print("[dim]Skipped.[/]")

    backfill_user_accepted(resp.routing_decision.query_hash, accepted)


def _display_response_meta(resp) -> None:
    """Print metadata table for a completed response."""
    # Routing badge (T-116)
    if getattr(resp, "routing_trace", None) and resp.routing_trace.get("badge"):
        console.print(f"[dim]{resp.routing_trace['badge']}[/dim]")

    if resp.contradiction and resp.contradiction.has_contradiction:
        console.print(f"[bold red][{resp.contradiction.contradiction_type.upper()} CONTRADICTION][/]")
        console.print(f"[red]{resp.contradiction.explanation}[/]")
        console.print()

    meta = Table(show_header=False, box=None, padding=(0, 2))
    meta.add_column("Key", style="dim")
    meta.add_column("Value")
    meta.add_row("Route", f"[green]{resp.route.value}[/]" if resp.route.value == "local" else f"[yellow]{resp.route.value}[/]")
    meta.add_row("Model", resp.model_used)
    if resp.confidence is not None:
        meta.add_row("Confidence", f"{resp.confidence:.1f}%")
    if resp.routing_decision and resp.routing_decision.reason:
        meta.add_row("Reason", resp.routing_decision.reason)
    console.print(meta)


def _display_query_debug(resp, query_text: str) -> None:
    """Show full routing cascade diagnostics for --debug mode."""
    console.print()
    console.print("[bold cyan]--- DEBUG: ROUTING CASCADE ---[/]")

    # PII
    console.print(f"  PII scrubbed:     {'YES' if resp.pii_scrubbed else 'no'}")

    # Complexity pre-score (re-run for diagnostics)
    try:
        from core.cognition.complexity import score_complexity
        cx = score_complexity(query_text)
        signals = ", ".join(cx["signals"]) if cx["signals"] else "none"
        console.print(f"  Complexity:       penalty={cx['penalty']:.0f}  skip_local={cx['skip_local']}")
        console.print(f"                    signals=[{signals}]")
        if cx["domains_matched"]:
            console.print(f"                    domains={cx['domains_matched']}")
    except Exception:
        console.print("  Complexity:       [dim]unavailable[/]")

    # Routing decision
    rd = resp.routing_decision
    if rd:
        console.print(f"  Route:            [bold]{rd.route.value}[/]")
        console.print(f"  Reason:           {rd.reason}")
        console.print(f"  Cosine gate:      {rd.cosine_gate_fired}")
        if rd.confidence:
            console.print(f"  Pre-route conf:   {rd.confidence.score:.1f}% ({rd.confidence.method})")

    # NLI
    if resp.contradiction:
        c = resp.contradiction
        console.print(f"  NLI:              [bold red]{c.contradiction_type}[/] (conf={c.confidence:.0f}%)")
        console.print(f"                    {c.explanation}")
    else:
        console.print("  NLI:              [dim]no contradiction[/]")

    # Final
    console.print(f"  Model:            {resp.model_used}")
    console.print(f"  Confidence:       {resp.confidence:.1f}%" if resp.confidence is not None else "  Confidence:       N/A")
    console.print()


@main.command()
@click.argument("query")
@click.option("--local-only", is_flag=True, help="Force local inference regardless of confidence")
@click.option("--cloud", is_flag=True, help="Force cloud inference (bypasses confidence routing)")
@click.option("--provider", type=str, default=None, help="Provider name (e.g., local, claude, openai)")
@click.option("--model", type=str, default=None, help="Model override (e.g., gpt-4o, qwen2.5:7b)")
@click.option("--no-scrub", is_flag=True, help="Skip PII detection/scrubbing")
@click.option("--no-stream", is_flag=True, help="Disable streaming (blocking mode)")
@click.option("--debug", is_flag=True, help="Show routing cascade diagnostics")
@click.option("-y", "--yes", is_flag=True, help="Auto-accept response (no prompt)")
def query(query: str, local_only: bool, cloud: bool, provider: str | None, model: str | None, no_scrub: bool, no_stream: bool, debug: bool, yes: bool):
    """Run a query through the full handler pipeline."""
    if local_only and cloud:
        console.print("[red]Cannot use --local-only and --cloud together.[/]")
        return

    # --provider implies cloud routing (unless it's "local")
    if provider and provider != "local":
        cloud = True

    # Build extra kwargs for provider/model override (T-047)
    extra_kwargs = {}
    if provider:
        extra_kwargs["cloud_name"] = provider
    if model:
        extra_kwargs["model_override"] = model

    if no_stream:
        from rich.status import Status

        from core.cognition.handler import execute_query
        from core.interface.thinking import get_thinking_indicator

        with Status(f"[oikos.dim]{get_thinking_indicator()}[/]", spinner="dots", console=console):
            resp = execute_query(query, force_local=local_only, force_cloud=cloud, skip_pii_scrub=no_scrub, **extra_kwargs)

        if resp.pii_scrubbed:
            console.print("[bold yellow][PII DETECTED AND SCRUBBED][/]")

        console.print()
        console.print(resp.text)
        console.print()
        _display_response_meta(resp)
        if debug:
            _display_query_debug(resp, query)
        _collect_feedback(resp, auto_accept=yes)
    else:
        from rich.live import Live
        from rich.text import Text
        from core.cognition.handler import execute_query_stream

        from core.interface.thinking import get_thinking_indicator

        console.print(f"[oikos.dim]{get_thinking_indicator()}[/]")
        output_parts: list[str] = []
        resp = None

        with Live("", console=console, refresh_per_second=10) as live:
            for chunk in execute_query_stream(query, force_local=local_only, force_cloud=cloud, skip_pii_scrub=no_scrub, **extra_kwargs):
                if chunk["done"]:
                    resp = chunk["response"]
                    break
                output_parts.append(chunk["delta"])
                live.update(Text("".join(output_parts)))

        if resp:
            if resp.pii_scrubbed:
                console.print("[bold yellow][PII DETECTED AND SCRUBBED][/]")

            _display_response_meta(resp)
            if debug:
                _display_query_debug(resp, query)
            _collect_feedback(resp, auto_accept=yes)


@main.group()
def test():
    """System test suite — integration, gauntlet, adversarial."""
    pass


@test.command("integration")
def test_integration():
    """Run automated end-to-end integration probes (pytest)."""
    console.print("[bold]Running Integration Test Harness (pytest)...[/]")
    try:
        result = subprocess.run(["pytest", "tests/test_integration.py"], check=True)
        if result.returncode == 0:
            console.print("[bold green]All 10 probes passed.[/]")
    except subprocess.CalledProcessError as e:
        console.print(f"[bold red]Integration tests failed (exit {e.returncode}).[/]")


@test.command("gauntlet")
def test_gauntlet():
    """Run identity and security gauntlet (delegates to oikos gauntlet)."""
    _run_gauntlet_display()


@main.command()
def gauntlet():
    """Run the adversarial gauntlet — 10 static probes with regression detection."""
    _run_gauntlet_display()


def _ensure_ollama() -> None:
    """Check Ollama connectivity; start it if not reachable."""
    import time
    import httpx

    try:
        httpx.get("http://localhost:11434/api/tags", timeout=2)
        return
    except (httpx.ConnectError, httpx.TimeoutException):
        pass

    console.print("[dim]Ollama not running — starting...[/]")
    subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    for _ in range(15):
        time.sleep(1)
        try:
            httpx.get("http://localhost:11434/api/tags", timeout=2)
            console.print("[green]Ollama ready.[/]")
            return
        except (httpx.ConnectError, httpx.TimeoutException):
            continue

    console.print("[bold red]Failed to start Ollama after 15s. Gauntlet may fail.[/]")


def _run_gauntlet_display() -> None:
    """Shared gauntlet execution and Rich display."""
    from rich.status import Status
    from core.agency.adversarial import run_gauntlet, get_briefing_items

    _ensure_ollama()

    with Status("", console=console) as status:
        def _progress(msg: str) -> None:
            status.update(f"[dim]{msg}[/]")

        summary = run_gauntlet(on_progress=_progress)

    _VERDICT_STYLE = {"PASS": "[green]PASS[/]", "SOFT_FAIL": "[yellow]SOFT_FAIL[/]", "HARD_FAIL": "[bold red]HARD_FAIL[/]"}


    table = Table(show_lines=True)
    table.add_column("ID", width=6)
    table.add_column("Probe Query", width=40)
    table.add_column("Verdict", width=12)
    table.add_column("Reasons", width=40)

    for r in summary.results:
        verdict_str = _VERDICT_STYLE.get(r.verdict, r.verdict)
        if r.regression:
            verdict_str += " [bold red][REG][/]"
        reasons = ", ".join(r.reasons) if r.reasons else "—"
        table.add_row(r.probe_id, r.query[:40], verdict_str, reasons)

    console.print(Panel(table, title="\u25c8 Gauntlet Results", box=box.DOUBLE, border_style="oikos.border"))
    console.print(
        f"\n[bold]Total:[/] {summary.total}  "
        f"[green]PASS:[/] {summary.passed}  "
        f"[yellow]SOFT_FAIL:[/] {summary.soft_fails}  "
        f"[red]HARD_FAIL:[/] {summary.hard_fails}"
    )
    if summary.regressions:
        console.print(f"[bold red]REGRESSIONS: {summary.regressions}[/]")

    # Briefing items for non-PASS
    briefing = get_briefing_items(summary)
    if briefing:
        console.print("\n[bold yellow]--- BRIEFING ITEMS ---[/]")
        for item in briefing:
            console.print(f"  {item}")


@main.command()
def evaluate():
    """Run context retrieval evaluation harness (Eval Agent)."""
    from rich.status import Status
    from core.agency.eval import run_eval

    _VERDICT_STYLE = {"PASS": "[green]PASS[/]", "MARGINAL": "[yellow]MARGINAL[/]", "FAIL": "[bold red]FAIL[/]"}

    with Status("", console=console) as status:
        def _progress(msg: str) -> None:
            status.update(f"[dim]{msg}[/]")

        summary = run_eval(on_progress=_progress)

    if summary["total"] == 0:
        console.print("[yellow]No queries evaluated.[/]")
        return

    table = Table(title="Evaluation Results (LLM-as-judge, 3-dim)", show_lines=True)
    table.add_column("ID", width=6)
    table.add_column("Query", width=35)
    table.add_column("Prec", width=6, justify="right")
    table.add_column("Recall", width=6, justify="right")
    table.add_column("Relevance", width=12)
    table.add_column("Score", width=6, justify="right")
    table.add_column("Verdict", width=10)

    for r in summary["results"]:
        verdict_str = _VERDICT_STYLE.get(r["verdict"], r["verdict"])
        table.add_row(
            r["eval_id"],
            r["query"][:35],
            f"{r['context_precision']:.0%}",
            f"{r['context_recall']:.0%}",
            r["answer_relevance"],
            f"{r['overall_score']:.2f}",
            verdict_str,
        )

    console.print(table)
    console.print(
        f"\n[bold]Total:[/] {summary['total']}  "
        f"[green]PASS:[/] {summary['passed']}  "
        f"[yellow]MARGINAL:[/] {summary['marginal']}  "
        f"[red]FAIL:[/] {summary['failed']}  "
        f"Avg: {summary['avg_score']:.2f}"
    )


@main.command()
def promote():
    """Review and apply pending memory consolidation proposals."""
    from core.agency.consolidation import load_pending_proposals, mark_proposal_status
    
    proposals = load_pending_proposals()
    if not proposals:
        console.print("[yellow]No pending proposals.[/]")
        return
        
    console.print(f"[bold]--- {len(proposals)} PENDING PROPOSALS ---[/]")
    if not sys.stdin.isatty():
        console.print("[yellow]Non-interactive mode — run 'oikos promote' in a terminal to review.[/]")
        return

    for prop in proposals:
        console.print(f"\n[bold]{prop.action}[/] {prop.target_path}")
        if prop.target_section:
            console.print(f"[dim]Section:[/] {prop.target_section}")
        console.print(f"[dim]Claim:[/] {prop.draft_content}")
        if prop.conflict_with:
            console.print(f"[yellow]Conflict with:[/] {prop.conflict_with}")

        console.print("[dim]Action:[/] [bold green]y[/]es  [bold red]n[/]o  [bold yellow]s[/]kip")
        try:
            ch = click.getchar()
            if ch in ("y", "Y"):
                mark_proposal_status(prop.proposal_id, "approved", apply=True)
                console.print("[green]Applied.[/]")
            elif ch in ("n", "N"):
                mark_proposal_status(prop.proposal_id, "rejected", apply=False)
                console.print("[red]Rejected.[/]")
            else:
                console.print("[yellow]Skipped.[/]")
        except (EOFError, KeyboardInterrupt, OSError):
            break
    console.print("\n[bold]Done.[/]")


@main.group()
def consolidate():
    """Memory consolidation agent — scan, propose, review."""
    pass


@consolidate.command("run")
def consolidate_run():
    """Scan session logs and generate vault promotion proposals."""
    from rich.status import Status
    from core.agency.consolidation import run_consolidation

    with Status("", console=console) as status:
        def _progress(msg: str) -> None:
            status.update(f"[dim]{msg}[/]")

        result = run_consolidation(on_progress=_progress)

    console.print(
        f"[green]Done.[/] "
        f"files={result['files_processed']}  "
        f"proposals={result['proposals_generated']}"
    )


@consolidate.command("review")
def consolidate_review():
    """Interactive review of pending consolidation proposals."""
    from core.agency.consolidation import load_pending_proposals, mark_proposal_status

    proposals = load_pending_proposals()
    if not proposals:
        console.print("[yellow]No pending proposals.[/]")
        return

    console.print(f"[bold]--- {len(proposals)} PENDING PROPOSALS ---[/]")
    if not sys.stdin.isatty():
        console.print("[yellow]Non-interactive mode — run in a terminal to review.[/]")
        return

    for prop in proposals:
        console.print(f"\n[bold]{prop.action}[/] {prop.target_path}")
        if prop.target_section:
            console.print(f"[dim]Section:[/] {prop.target_section}")
        console.print(f"[dim]Claim:[/] {prop.draft_content}")
        if prop.strategic_divergence:
            console.print("[bold red][STRATEGIC DIVERGENCE] This contradicts GOALS.md or MISSION.md[/]")
        if prop.conflict_with:
            console.print(f"[yellow]Conflict with:[/] {prop.conflict_with}")
        if prop.insight_type == "lesson":
            console.print("[cyan]Type: LESSON (→ LEARNINGS.md)[/]")

        console.print("[dim]Action:[/] [bold green]y[/]es  [bold red]n[/]o  [bold yellow]s[/]kip")
        try:
            ch = click.getchar()
            if ch in ("y", "Y"):
                mark_proposal_status(prop.proposal_id, "approved", apply=True)
                console.print("[green]Applied.[/]")
            elif ch in ("n", "N"):
                mark_proposal_status(prop.proposal_id, "rejected", apply=False)
                console.print("[red]Rejected.[/]")
            else:
                console.print("[yellow]Skipped.[/]")
        except (EOFError, KeyboardInterrupt, OSError):
            break
    console.print("\n[bold]Done.[/]")


@main.command()
def idle():
    """Transition to IDLE — run maintenance tasks (re-index, scanner, git)."""
    from core.autonomic.fsm import get_current_state, transition_to
    from core.interface.models import SystemState

    current = get_current_state()
    if current == SystemState.IDLE:
        console.print("[dim]Already IDLE.[/]")
        return

    try:
        result = transition_to(SystemState.IDLE, trigger="cli:idle")
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        return

    # Display callback results
    if result.get("reindex"):
        stats = result["reindex"]
        console.print(
            f"Re-index: files={stats.get('files', 0)} "
            f"added={stats.get('added', 0)} "
            f"skipped={stats.get('skipped', 0)}"
        )
    elif result.get("reindex_error"):
        console.print(f"[yellow]Re-index skipped: {result['reindex_error']}[/]")

    if result.get("consolidation"):
        consol = result["consolidation"]
        console.print(f"Consolidation: processed {consol.get('files_processed', 0)} files, generated {consol.get('proposals_generated', 0)} proposals.")
    elif result.get("consolidation_error"):
        console.print(f"[yellow]Consolidation failed: {result['consolidation_error']}[/]")

    if result.get("scanner"):
        scan = result["scanner"]
        blip_count = len(scan.get("blips", []))
        evaluated = scan.get("pairs_evaluated", 0)
        if blip_count:
            console.print(f"Scanner: {blip_count} connection(s) found from {evaluated} pairs.")
        else:
            console.print(f"Scanner: evaluated {evaluated} pairs, no connections above threshold.")
    elif result.get("scanner_inactive"):
        console.print(f"[dim]Scanner inactive: {result['scanner_inactive']}[/]")

    git = result.get("git", {})
    if git.get("committed"):
        console.print(f"Git: committed {len(git.get('files', []))} vault file(s).")
    else:
        console.print("[dim]Git: no vault changes.[/]")

    console.print(f"\n[bold]State: IDLE.[/] Standing by.")


@main.command()
def wake():
    """Transition to ACTIVE — deliver session briefing."""
    from core.autonomic.fsm import get_current_state, transition_to
    from core.interface.models import SystemState

    current = get_current_state()
    if current == SystemState.ACTIVE:
        console.print("[dim]Already ACTIVE.[/]")
        return

    try:
        transition_to(SystemState.ACTIVE, trigger="cli:wake")
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        return

    _deliver_briefing()
    console.print("[bold]State: ACTIVE.[/]")


@main.command()
def sleep():
    """Transition to ASLEEP — flush pending writes."""
    from core.autonomic.fsm import get_current_state, transition_to
    from core.interface.models import SystemState

    current = get_current_state()
    if current == SystemState.ASLEEP:
        console.print("[dim]Already ASLEEP.[/]")
        return

    try:
        transition_to(SystemState.ASLEEP, trigger="cli:sleep")
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        return

    console.print("[bold]State: ASLEEP.[/]")


@main.command()
def state():
    """Display current FSM state."""
    from core.autonomic.fsm import get_current_state, get_last_transition_time

    current = get_current_state()
    last = get_last_transition_time()

    state_colors = {"active": "green", "idle": "yellow", "asleep": "dim"}
    color = state_colors.get(current.value, "white")
    console.print(f"State: [{color}]{current.value.upper()}[/]")
    if last:
        console.print(f"Last transition: {last}")


def _deliver_briefing() -> None:
    """Load and display undelivered blips + drift nudges."""

    blips = []
    nudges = []

    try:
        from core.autonomic.scanner import load_undelivered_blips, mark_blips_delivered
        blips = load_undelivered_blips()
    except Exception as e:
        log.debug("blip load suppressed: %s", e)

    try:
        from core.autonomic.drift import generate_nudges
        nudges = generate_nudges()
    except Exception as e:
        log.debug("nudge generation suppressed: %s", e)

    proposals = []
    try:
        from core.agency.consolidation import load_pending_proposals, mark_proposal_status
        proposals = load_pending_proposals()
    except Exception as e:
        log.debug("proposal load suppressed: %s", e)

    if not blips and not nudges and not proposals:
        return  # Clean entry, no noise

    from core.interface.models import EscalationTier

    # INTERVENTION nudges first (mandatory acknowledgment)
    interventions = [n for n in nudges if n.tier == EscalationTier.INTERVENTION]
    advisories = [n for n in nudges if n.tier == EscalationTier.ADVISORY]
    soft_nudges = [n for n in nudges if n.tier == EscalationTier.NUDGE]

    console.print()
    console.print("[bold]--- SESSION BRIEFING ---[/]")
    console.print()

    if proposals:
        console.print("[bold cyan]--- MEMORY CONSOLIDATION PROPOSALS ---[/]")
        for prop in proposals:
            console.print(f"\n[bold]{prop.action}[/] {prop.target_path}")
            console.print(f"[dim]Claim:[/] {prop.draft_content}")
            if prop.conflict_with:
                console.print(f"[yellow]Conflict:[/] {prop.conflict_with}")

            if not sys.stdin.isatty():
                console.print("[yellow]Non-interactive — skipped.[/]")
                continue

            console.print("[dim]Approve this proposal? [bold green]y[/]es  [bold red]n[/]o  [bold yellow]s[/]kip[/]")
            try:
                ch = click.getchar()
                if ch in ("y", "Y"):
                    mark_proposal_status(prop.proposal_id, "APPLIED", apply=True)
                    console.print("[green]Applied to vault.[/]")
                elif ch in ("n", "N"):
                    mark_proposal_status(prop.proposal_id, "REJECTED", apply=False)
                    console.print("[red]Rejected.[/]")
                else:
                    console.print("[yellow]Skipped for now.[/]")
            except (EOFError, KeyboardInterrupt, OSError):
                console.print("[yellow]Skipped.[/]")
        console.print()

    if interventions:
        for n in interventions:
            console.print(f"  [bold red][INTERVENTION] {n.message}[/]")
        console.print()
        if sys.stdin.isatty():
            console.print("[bold red]INTERVENTION requires acknowledgment.[/]")
            console.print("[dim]Press any key to continue.[/]")
            try:
                click.getchar()
            except (EOFError, KeyboardInterrupt, OSError):
                pass

    for n in advisories:
        console.print(f"  [bold yellow][ADVISORY] {n.message}[/]")

    for n in soft_nudges:
        console.print(f"  [dim yellow][NUDGE] {n.message}[/]")

    if nudges:
        console.print()

    # Blips
    if blips:
        for blip in blips:
            resonance_str = f"{blip.resonance:.0f}" if blip.resonance is not None else "unvalidated"
            panel_content = (
                f"{blip.observation}\n\n"
                f"[dim]Source A:[/] {blip.chunk_a.get('source_path', '?')} ({blip.chunk_a.get('tier', '?')})\n"
                f"[dim]Source B:[/] {blip.chunk_b.get('source_path', '?')} ({blip.chunk_b.get('tier', '?')})\n"
                f"[dim]Resonance:[/] {resonance_str}"
            )
            console.print(Panel(panel_content, title="[cyan]Pattern Blip[/]", border_style="cyan"))

        try:
            mark_blips_delivered([b.blip_id for b in blips])
        except Exception as e:
            log.debug("blip delivery mark suppressed: %s", e)

    try:
        from core.identity.assertions import load_undelivered_assertions, mark_assertions_delivered
        undelivered = load_undelivered_assertions()
        if undelivered:
            count = len(undelivered)
            console.print(
                f"[yellow]{count} new assertion{'s' if count > 1 else ''} logged since last session.[/] "
                f"Review with [cyan]oikos assertions[/]."
            )
            mark_assertions_delivered([e["id"] for e in undelivered])
    except Exception as e:
        log.debug("assertion delivery suppressed: %s", e)

    console.print("[dim]--- END BRIEFING ---[/]")
    console.print()


@main.group()
def session():
    """Session management."""
    pass


@session.command("close")
def session_close():
    """Explicitly close the current session."""
    from core.memory.session import close_session

    state = close_session()
    if state is None:
        console.print("[yellow]No active session.[/]")
        return

    console.print(
        f"[green]Session closed.[/] "
        f"id={state['session_id']}  "
        f"interactions={state.get('interaction_count', 0)}"
    )


main.add_command(session)


@main.command()
@click.option("--port", default=8420, help="Port to bind (default 8420)")
@click.option("--dev", is_flag=True, help="Enable CORS for localhost:5173 + API docs")
@click.option("--room", "room_id", default=None, help="Switch to this room before starting")
@click.option("--no-boot", is_flag=True, help="Skip boot animation (CI mode)")
@click.option("--theme", type=click.Choice(["amber", "green", "white"]), default=None, help="Phosphor color theme (session override)")
def serve(port: int, dev: bool, room_id: str | None, no_boot: bool, theme: str | None):
    """Start the OIKOS API server."""
    if theme:
        from core.interface.theme import apply_theme
        apply_theme(theme)

    from core.onboarding.state import is_onboarding_complete

    if not is_onboarding_complete():
        console.print("[yellow]oikOS hasn't been set up yet.[/]")
        console.print(f"[dim]Run 'oikos setup' or visit http://localhost:{port} for the guided wizard.[/]\n")

    if room_id:
        from core.rooms.manager import get_room_manager
        mgr = get_room_manager()
        try:
            mgr.switch_room(room_id)
            console.print(f"  Switched to room: [bold]{room_id}[/]")
        except ValueError as e:
            console.print(f"[red]{e}[/]")
            raise SystemExit(1)

    # Auto-start daemon if not already running
    from core.autonomic.daemon import is_running as daemon_is_running, start as daemon_start

    if not daemon_is_running():
        daemon_start(foreground=False)
        console.print("  [dim]Daemon started.[/]")

    if not no_boot:
        from core.interface.boot import run_boot_sequence

        run_boot_sequence(console, port=port, dev=dev)

    from core.interface.api.server import run_server

    # In dev mode, start Vite dev server for frontend hot-reload
    vite_proc = None
    if dev:
        import atexit
        import subprocess as _sp

        from core.interface.config import PROJECT_ROOT
        frontend_dir = PROJECT_ROOT / "frontend"
        if (frontend_dir / "package.json").exists():
            try:
                flags = 0
                if sys.platform == "win32":
                    flags = _sp.CREATE_NEW_PROCESS_GROUP
                cmd = ["npx.cmd", "vite", "--host", "127.0.0.1"] if sys.platform == "win32" else ["npx", "vite", "--host", "127.0.0.1"]
                vite_proc = _sp.Popen(
                    cmd,
                    cwd=str(frontend_dir),
                    stdout=_sp.DEVNULL,
                    stderr=_sp.DEVNULL,
                    creationflags=flags,
                )
                console.print("  [dim]Vite dev server started (port 5173).[/]")

                def _kill_vite():
                    if vite_proc and vite_proc.poll() is None:
                        vite_proc.terminate()

                atexit.register(_kill_vite)
            except Exception as e:
                console.print(f"  [yellow]Vite dev server failed to start: {e}[/]")

    if not no_boot:
        import threading
        import webbrowser

        url = "http://localhost:5173" if dev else f"http://localhost:{port}"
        threading.Timer(1.5, webbrowser.open, args=[url]).start()
    run_server(port=port, dev=dev)


@main.command()
def calibrate():
    """Calibrate confidence threshold from feedback data."""
    from core.autonomic.calibration import calibration_report

    report = calibration_report()

    if report["status"] == "insufficient":
        console.print(
            f"[yellow]Insufficient data.[/] "
            f"{report['total_rated']} rated queries collected, "
            f"{report['min_required']} required."
        )
        return

    # Status
    status_color = "green" if report["status"] == "stable" else "yellow"
    console.print(f"Status: [{status_color}]{report['status'].upper()}[/] ({report['total_rated']} rated queries)")
    console.print(f"Skip rate: {report['skip_rate']:.1%}")
    console.print()

    # Accuracy curve
    table = Table(title="Accuracy by Confidence Bucket", show_lines=True)
    table.add_column("Range", width=10)
    table.add_column("Total", width=8, justify="right")
    table.add_column("Accepted", width=10, justify="right")
    table.add_column("Accuracy", width=10, justify="right")

    for bucket in report["curve"]:
        acc_str = f"{bucket['accuracy']:.1%}" if bucket["accuracy"] is not None else "—"
        table.add_row(bucket["range"], str(bucket["total"]), str(bucket["accepted"]), acc_str)

    console.print(table)
    console.print()

    # Recommendation
    console.print(f"Current threshold: [bold]{report['current_threshold']}%[/]")
    if report["recommended_threshold"] is not None:
        console.print(f"Recommended threshold: [bold green]{report['recommended_threshold']:.1f}%[/]")
        console.print("[dim]To apply: update ROUTING_CONFIDENCE_THRESHOLD in core/config.py[/]")
    else:
        console.print("[yellow]Could not compute recommendation.[/]")


@main.command()
def credits():
    """Show credit balance and usage."""
    from core.safety.credits import load_credits

    balance = load_credits()

    table = Table(title="Credit Balance", show_lines=True)
    table.add_column("Metric", width=15)
    table.add_column("Value", width=15, justify="right")

    table.add_row("Monthly Cap", str(balance.monthly_cap))
    table.add_row("Used", str(balance.used))
    table.add_row("Remaining", str(balance.remaining))
    table.add_row("Last Reset", balance.last_reset[:10])

    if balance.in_deficit:
        table.add_row("[bold red]DEFICIT[/]", f"[bold red]{balance.deficit}[/]")

    console.print(table)

    if balance.in_deficit:
        console.print("\n[bold red]WARNING: COGNITIVE OVERRUN — credit deficit active.[/]")


@main.command()
def info():
    """Display system info — neofetch style."""
    from core.interface.info import render_info

    render_info(console)


@main.command()
def status():
    """Show Ollama health, index stats, and handler subsystems."""

    from core.memory.embedder import check_health
    from core.memory.indexer import get_table_stats

    console.print(Panel("[oikos.header]oikOS STATUS[/]", box=box.DOUBLE, border_style="oikos.border", expand=True))

    # Embedding health
    health = check_health()
    health_str = "[green]OK[/]" if health else "[red]OFFLINE[/]"
    console.print(f"Ollama Embed: {health_str}")

    # Index stats
    stats = get_table_stats()
    console.print(f"Index:        {stats['total_rows']} chunks, {stats['unique_files']} files")
    if stats["tier_breakdown"]:
        for tier, count in sorted(stats["tier_breakdown"].items()):
            console.print(f"  {tier}: {count}")

    # Inference model
    from core.cognition.inference import check_inference_model, check_logprob_support
    from core.interface.config import INFERENCE_MODEL

    inf_ok = check_inference_model()
    inf_str = f"[green]{INFERENCE_MODEL}[/]" if inf_ok else f"[red]NOT FOUND ({INFERENCE_MODEL})[/]"
    console.print(f"Inference:    {inf_str}")

    if inf_ok:
        lp_ok = check_logprob_support()
        lp_str = "[green]YES[/]" if lp_ok else "[yellow]NO (degraded confidence)[/]"
        console.print(f"Logprobs:     {lp_str}")

    # PII engine
    try:
        from core.safety.pii import get_analyzer
        get_analyzer()
        console.print("PII Engine:   [green]LOADED[/]")
    except Exception:
        console.print("PII Engine:   [red]NOT LOADED[/]")

    # Credits
    from core.safety.credits import load_credits
    bal = load_credits()
    deficit_str = f" [bold red](DEFICIT: {bal.deficit})[/]" if bal.in_deficit else ""
    console.print(f"Credits:      {bal.used}/{bal.monthly_cap} used{deficit_str}")

    # Cloud bridge
    import os
    from core.interface.config import CLOUD_MODEL, CLOUD_HARD_CEILING_MULTIPLIER
    cloud_key = bool(os.environ.get("GEMINI_API_KEY"))
    cloud_str = f"[green]ACTIVE ({CLOUD_MODEL})[/]" if cloud_key else "[yellow]NO API KEY[/]"
    console.print(f"Cloud Bridge: {cloud_str}")
    hard_ceiling = bal.monthly_cap * CLOUD_HARD_CEILING_MULTIPLIER
    ceiling_remaining = hard_ceiling - bal.used
    ceiling_str = f"[green]{ceiling_remaining:.0f}[/]" if ceiling_remaining > 0 else "[bold red]BREACHED[/]"
    console.print(f"Hard Ceiling: {ceiling_str} remaining (ceiling={hard_ceiling:.0f})")

    # Drift detector diagnostic + nudges
    try:
        from core.autonomic.drift import drift_diagnostic, generate_nudges

        diag = drift_diagnostic()
        if diag["active_deadlines"] == 0:
            console.print("Drift:        [yellow]NO DEADLINES PARSED — detector inactive[/]")
        else:
            console.print(
                f"Drift:        {diag['active_deadlines']} active deadlines, "
                f"{diag['domains_tracked']} domains tracked"
            )

        nudges = generate_nudges()
        if nudges:
            from core.interface.models import EscalationTier

            console.print()
            console.print("[bold yellow]--- DRIFT DETECTED ---[/]")
            for nudge in nudges:
                if nudge.tier == EscalationTier.INTERVENTION:
                    console.print(f"  [bold red][INTERVENTION] {nudge.message}[/]")
                elif nudge.tier == EscalationTier.ADVISORY:
                    console.print(f"  [bold yellow][ADVISORY] {nudge.message}[/]")
                else:
                    console.print(f"  [yellow][NUDGE] {nudge.message}[/]")

            if any(n.tier == EscalationTier.INTERVENTION for n in nudges):
                console.print()
                console.print("[bold red]INTERVENTION requires acknowledgment.[/]")
                if sys.stdin.isatty():
                    console.print("[dim]Press [bold]y[/] to acknowledge, [bold]d[/] to dismiss with reason, any other key to skip.[/]")
                    try:
                        ch = click.getchar()
                        if ch == "d":
                            from core.autonomic.drift import record_dismissal
                            try:
                                reason = click.prompt("Reason", default="")
                            except (EOFError, KeyboardInterrupt, OSError):
                                reason = ""
                            for n in nudges:
                                if n.tier == EscalationTier.INTERVENTION:
                                    record_dismissal(n.pattern_id, reason or None)
                    except (EOFError, KeyboardInterrupt, OSError):
                        pass
    except Exception as e:
        log.debug("drift detector suppressed: %s", e)

    # FSM state
    try:
        from core.autonomic.fsm import get_current_state, get_last_transition_time

        fsm_state = get_current_state()
        fsm_colors = {"active": "green", "idle": "yellow", "asleep": "dim"}
        fsm_color = fsm_colors.get(fsm_state.value, "white")
        last_ts = get_last_transition_time()
        ts_str = f" (since {last_ts[:19]})" if last_ts else ""
        console.print(f"FSM State:    [{fsm_color}]{fsm_state.value.upper()}[/]{ts_str}")
    except Exception as e:
        log.debug("FSM state display suppressed: %s", e)

    # Scanner status
    try:
        from core.autonomic.scanner import check_activation_gate, load_undelivered_blips
        from core.interface.config import SCANNER_BLIP_LOG

        gate = check_activation_gate()
        gate_str = "[green]ACTIVE[/]" if gate["active"] else f"[yellow]INACTIVE ({gate['reason']})[/]"
        console.print(f"Scanner:      {gate_str}")

        blips = load_undelivered_blips()
        console.print(f"Blips:        {len(blips)} undelivered")

        if SCANNER_BLIP_LOG.exists():
            import os
            from datetime import datetime, timezone
            mtime = datetime.fromtimestamp(os.path.getmtime(SCANNER_BLIP_LOG), tz=timezone.utc)
            console.print(f"Last Scan:    {mtime.isoformat()[:19]}")
    except Exception as e:
        log.debug("scanner status display suppressed: %s", e)


@main.group("daemon")
def daemon_group():
    """OS daemon management."""
    pass


@daemon_group.command("start")
@click.option("--foreground", is_flag=True, help="Run in foreground (blocking)")
def daemon_start(foreground: bool):
    """Start the OIKOS daemon."""
    from core.autonomic.daemon import is_running, start

    if is_running():
        console.print("[yellow]Daemon already running.[/]")
        return

    if foreground:
        console.print("[bold]Starting daemon (foreground)...[/]")
        start(foreground=True)
    else:
        start(foreground=False)
        console.print("[green]Daemon launched in background.[/]")


@daemon_group.command("stop")
def daemon_stop():
    """Stop the OIKOS daemon."""
    from core.autonomic.daemon import is_running

    if not is_running():
        console.print("[yellow]Daemon not running.[/]")
        return

    from core.interface.config import DAEMON_PID_FILE, DAEMON_STOP_FILE

    try:
        pid = int(DAEMON_PID_FILE.read_text(encoding="utf-8").strip())
        DAEMON_STOP_FILE.write_text("stop", encoding="utf-8")
        # Wait for daemon to pick up the stop file (up to 2 heartbeat cycles)
        for _ in range(12):
            time.sleep(5)
            if not is_running():
                console.print(f"[green]Daemon stopped (PID {pid}).[/]")
                return
        console.print("[yellow]Daemon did not stop within timeout — force killing.[/]")
        if sys.platform == "win32":
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(1, False, pid)  # PROCESS_TERMINATE
            if handle:
                kernel32.TerminateProcess(handle, 0)
                kernel32.CloseHandle(handle)
        else:
            os.kill(pid, signal.SIGKILL)
        DAEMON_PID_FILE.unlink(missing_ok=True)
        DAEMON_STOP_FILE.unlink(missing_ok=True)
        console.print(f"[green]Daemon force-killed (PID {pid}).[/]")
    except (ValueError, OSError) as e:
        console.print(f"[red]Failed to stop daemon: {e}[/]")


@daemon_group.command("install")
def daemon_install():
    """Register daemon as Windows logon task."""
    from core.autonomic.daemon import install_service

    try:
        install_service()
        console.print("[green]OIKOS_DAEMON registered (logon trigger).[/]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Failed: {e}[/]")


@daemon_group.command("uninstall")
def daemon_uninstall():
    """Remove daemon from Windows Task Scheduler."""
    from core.autonomic.daemon import uninstall_service

    try:
        uninstall_service()
        console.print("[green]OIKOS_DAEMON removed from Task Scheduler.[/]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Failed: {e}[/]")


@daemon_group.command("status")
def daemon_status():
    """Show daemon status."""
    from core.autonomic.daemon import get_status

    status = get_status()

    if status["running"]:
        console.print(f"[green]RUNNING[/] (PID {status['pid']})")
        if status["uptime_seconds"] is not None:
            mins = status["uptime_seconds"] / 60
            console.print(f"Uptime:       {mins:.1f} min")
    else:
        console.print("[dim]NOT RUNNING[/]")

    console.print(f"FSM State:    {status['fsm_state'].upper()}")
    console.print(f"Inference:    {status['inference_manager'] or 'none'}")
    console.print(f"Restarts:     {status['restart_attempts']}")


@main.command("vault-check")
def vault_check():
    """Scan vault files for stale frontmatter dates and missing metadata."""
    from core.freshness import vault_freshness

    report = vault_freshness.run(console=console)
    if report["stale"] == 0 and report["missing_frontmatter"] == 0:
        console.print("[green]All vault files current.[/]")


@main.command("sync-check")
def sync_check():
    """Check sync manifest for drifted cross-platform files."""
    from core.freshness import sync_manifest

    sync_manifest.run(console=console)


@main.group(cls=SmartGroup, invoke_without_command=True)
@click.pass_context
def provider(ctx):
    """Manage inference providers."""
    if ctx.invoked_subcommand is not None:
        return

    from core.cognition.pipeline.dispatch import get_provider_registry

    reg = get_provider_registry()
    default_name = reg.get_default_name()

    table = Table(show_header=False, box=None, pad_edge=False, show_edge=False)
    table.add_column("", width=12)
    table.add_column("Provider", style="oikos.primary")
    table.add_column("Status", style="dim")

    for name in reg.list_all():
        p = reg.get(name)
        status = "[oikos.success]available[/]" if p.is_available() else "[dim]stopped[/]"
        marker = "[oikos.bright]◂ active[/]" if name == default_name else ""
        table.add_row(marker, name, status)

    console.print(Panel(
        table,
        title=f"[oikos.header]◈ {default_name or 'none'}[/]",
        subtitle="[dim]oikos provider <name> to switch[/]",
        box=box.ROUNDED,
        border_style="oikos.border",
        padding=(1, 2),
    ))


@provider.command("list")
def provider_list():
    """List all registered providers and their availability."""

    from core.cognition.pipeline.dispatch import get_provider_registry
    from core.onboarding.detector import BACKEND_DISPLAY_NAMES

    reg = get_provider_registry()
    table = Table(show_header=True, header_style="oikos.header", show_lines=False)
    table.add_column("Provider", style="oikos.primary")
    table.add_column("Name", style="dim")
    table.add_column("Status")
    table.add_column("", width=10)

    for name in reg.list_all():
        p = reg.get(name)
        status = "[green]AVAILABLE[/]" if p.is_available() else "[red]UNAVAILABLE[/]"
        default = "[bold](default)[/]" if name == reg.get_default_name() else ""
        display = BACKEND_DISPLAY_NAMES.get(name, name)
        table.add_row(display, name, status, default)

    console.print(Panel(table, title="\u25c8 Providers", box=box.ROUNDED, border_style="oikos.border"))


@provider.command("test")
def provider_test():
    """Test connectivity to all configured providers."""
    from core.cognition.pipeline.dispatch import get_provider_registry
    from core.interface.models import ProviderMessage
    reg = get_provider_registry()
    for name in reg.list_all():
        p = reg.get(name)
        if not p.is_available():
            console.print(f"  {name}: [red]SKIP[/] (not configured)")
            continue
        try:
            msgs = [ProviderMessage(role="user", content="Say 'ok' in one word.")]
            resp = p.generate(msgs, max_tokens=10)
            if "[INFERENCE ERROR" in resp.text:
                console.print(f"  {name}: [red]FAIL[/] — {resp.text}")
            else:
                console.print(f"  {name}: [green]OK[/] ({resp.latency_ms}ms, {resp.model})")
        except Exception as e:
            console.print(f"  {name}: [red]FAIL[/] — {e}")


@provider.command("status")
def provider_status():
    """Show current provider configuration."""
    from core.interface.settings import get_setting
    console.print(f"  Default provider: [bold]{get_setting('provider_default')}[/]")
    console.print(f"  Cloud provider:   [bold]{get_setting('provider_cloud_default')}[/]")
    console.print(f"  Routing posture:  [bold]{get_setting('cloud_routing_posture')}[/]")

    from core.cognition.pipeline.dispatch import get_provider_registry
    reg = get_provider_registry()
    available = reg.list_available()
    console.print(f"  Available:        {', '.join(available) if available else 'none'}")


@provider.command("set")
@click.argument("key")
@click.argument("value")
def provider_set(key, value):
    """Set a provider configuration value (e.g., 'default local', 'posture balanced').

    Runtime overrides are saved to settings.json and take effect immediately.
    providers.toml remains the boot-time authority. Edit providers.toml directly
    for persistent changes across restarts.
    """
    from core.interface.settings import update_setting
    key_map = {
        "default": "provider_default",
        "cloud": "provider_cloud_default",
        "posture": "cloud_routing_posture",
        "model": "provider_anthropic_model",
    }
    setting_key = key_map.get(key)
    if not setting_key:
        console.print(f"[red]Unknown key: {key}. Valid: {', '.join(key_map)}[/]")
        return
    update_setting(setting_key, value)
    console.print(f"  {key} = {value} [green](saved)[/]")

    # If changing default provider, update the registry
    if key == "default":
        from core.cognition.pipeline.dispatch import get_provider_registry
        try:
            reg = get_provider_registry()
            reg.set_default(value)
        except KeyError:
            console.print(f"  [yellow]Warning: provider '{value}' not registered[/]")

    # If changing posture, invalidate cached router so it re-reads the setting
    if key == "posture":
        import core.cognition.handler as _h
        _h._provider_router = None


@provider.command("init")
def provider_init():
    """Generate a default providers.toml configuration file."""
    from core.cognition.providers.config_loader import generate_default_config
    path = generate_default_config()
    console.print(f"  providers.toml written to: [bold]{path}[/]")
    console.print("  Edit this file to configure providers, then restart oikOS.")


@provider.command("costs")
def provider_costs():
    """Show per-provider cost summary from query log."""
    from pathlib import Path
    from core.interface.config import PROJECT_ROOT
    cost_log = PROJECT_ROOT / "logs" / "costs" / "queries.jsonl"
    if not cost_log.exists():
        console.print("  No cost data yet. Run some queries first.")
        return

    import json
    from collections import defaultdict
    totals = defaultdict(lambda: {"queries": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
    for line in cost_log.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        p = entry.get("provider", "unknown")
        totals[p]["queries"] += 1
        totals[p]["input_tokens"] += entry.get("input_tokens", 0)
        totals[p]["output_tokens"] += entry.get("output_tokens", 0)
        totals[p]["cost_usd"] += entry.get("cost_usd", 0.0)

    console.print("[bold]Provider Cost Summary[/]")
    for name, data in sorted(totals.items()):
        console.print(
            f"  {name}: {data['queries']} queries | "
            f"{data['input_tokens']:,} in / {data['output_tokens']:,} out | "
            f"${data['cost_usd']:.4f}"
        )


PROVIDERS_TOML = None  # resolved lazily


def _get_providers_toml():
    global PROVIDERS_TOML
    if PROVIDERS_TOML is None:
        from core.interface.config import PROJECT_ROOT
        PROVIDERS_TOML = PROJECT_ROOT / "providers.toml"
    return PROVIDERS_TOML


@provider.command("_default", hidden=True)
@click.argument("provider_name")
def provider_switch_shorthand(provider_name):
    """Switch default provider (shorthand)."""
    from core.cognition.pipeline.dispatch import get_provider_registry

    reg = get_provider_registry()
    available = reg.list_all()
    if provider_name not in available:
        console.print(
            f"[oikos.error]No provider '{provider_name}' configured. "
            f"Run [bold]oikos provider[/bold] to see options.[/]"
        )
        raise SystemExit(1)

    import tomllib

    toml_path = _get_providers_toml()
    if toml_path.exists():
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
    else:
        data = {"general": {}, "providers": {}}

    data.setdefault("general", {})["default"] = provider_name

    lines = ["[general]"]
    for k, v in data["general"].items():
        lines.append(_toml_kv(k, v))
    lines.append("")
    for pname, pconfig in data.get("providers", {}).items():
        lines.append(f"[providers.{pname}]")
        for k, v in pconfig.items():
            lines.append(_toml_kv(k, v))
        lines.append("")
    toml_path.write_text("\n".join(lines), encoding="utf-8")

    console.print(f"[oikos.success]◈ Default provider changed to {provider_name}[/]")


# ── Room commands ──────────────────────────────────────────────────────


@main.group(cls=SmartGroup, invoke_without_command=True)
@click.pass_context
def room(ctx):
    """Manage oikOS Rooms — isolated contexts with scoped tools and vault access."""
    if ctx.invoked_subcommand is not None:
        return

    from core.rooms.manager import get_room_manager

    mgr = get_room_manager()
    active = mgr.get_active_room()
    rooms = mgr.list_rooms()

    table = Table(show_header=False, box=None, pad_edge=False, show_edge=False)
    table.add_column("", width=12)
    table.add_column("Room", style="oikos.primary")

    for r in rooms:
        marker = "[oikos.bright]◂ active[/]" if r.id == active.id else ""
        table.add_row(marker, r.id)

    from rich.text import Text as RichText
    from rich.console import Group as RichGroup

    header = RichText.from_markup(f"[oikos.bright]◈ {active.name}[/] [dim]({active.id})[/]")
    toolsets_str = ", ".join(active.toolsets) if active.toolsets else "all"
    info = RichText.from_markup(f"[dim]Toolsets    {toolsets_str}[/]")

    from core.interface.settings import get_setting

    # T-118: Generation params
    global_temp = get_setting("inference_temperature")
    global_max = get_setting("inference_max_tokens")
    room_temp = active.voice.temperature
    room_max = active.limits.max_tokens_per_query

    if room_temp is not None:
        temp_str = f"{room_temp}  [dim](global: {global_temp})[/]"
    else:
        temp_str = f"{global_temp}  [dim](default)[/]"

    if room_max is not None:
        max_str = f"{room_max}  [dim](global: {global_max})[/]"
    else:
        max_str = f"{global_max}  [dim](default)[/]"

    gen_info = RichText.from_markup(
        f"[dim]Temperature {temp_str}\n"
        f"Max tokens  {max_str}[/]"
    )

    console.print(Panel(
        RichGroup(header, "", info, gen_info, "", table),
        box=box.ROUNDED,
        border_style="oikos.border",
        padding=(1, 2),
    ))


@room.command("list")
def room_list():
    """List all rooms."""

    from core.rooms.manager import get_room_manager

    mgr = get_room_manager()
    rooms = mgr.list_rooms()
    active = mgr.get_active_room()

    table = Table(show_header=True, header_style="oikos.header", box=None, pad_edge=False)
    table.add_column("", width=2)
    table.add_column("ID", style="bold")
    table.add_column("Name")
    table.add_column("Toolsets")
    table.add_column("Description", style="dim")

    for r in rooms:
        marker = "[oikos.bright]▸[/]" if r.id == active.id else " "
        toolsets = ", ".join(r.toolsets) if r.toolsets else "all"
        table.add_row(marker, r.id, r.name, toolsets, r.description or "")

    panel = Panel(
        table,
        title="[oikos.header]⌂ ROOMS[/]",
        subtitle=f"[oikos.dim]{len(rooms)} rooms · Active: {active.id}[/]",
        border_style="oikos.border",
        box=box.DOUBLE,
    )
    console.print(panel)


@room.command("show")
@click.argument("room_id")
def room_show(room_id: str):
    """Show room details as JSON."""
    from core.rooms.manager import get_room_manager

    mgr = get_room_manager()
    try:
        r = mgr.get_room(room_id)
        click.echo(r.model_dump_json(indent=2))
        from core.rooms.limits import get_room_usage
        usage = get_room_usage(room_id)
        console.print(f"\n[dim]Monthly tokens: {usage['monthly_tokens']}[/]")
        console.print(f"[dim]Monthly cloud spend: {usage['monthly_cloud_spend_cents']}c[/]")
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        raise SystemExit(1)


@room.command("create")
@click.argument("room_id")
@click.option("--name", required=True, help="Display name")
@click.option("--description", default=None, help="Room description")
@click.option(
    "--template",
    type=click.Choice(["researcher", "code", "writing", "health", "finance"]),
    default=None,
    help="Start from a template",
)
def room_create(room_id: str, name: str, description: str | None, template: str | None):
    """Create a new room."""
    from core.rooms.defaults import TEMPLATES
    from core.rooms.manager import get_room_manager
    from core.rooms.models import RoomConfig

    mgr = get_room_manager()
    if template:
        data = {**TEMPLATES[template], "id": room_id}
        if name:
            data["name"] = name
        if description:
            data["description"] = description
    else:
        data = {"id": room_id, "name": name, "description": description}

    try:
        config = RoomConfig.model_validate(data)
        mgr.create_room(config)
        tmpl_info = f" (template: {template})" if template else ""
        console.print(
            Panel(
                f"Room [bold]{room_id}[/] created{tmpl_info}.",
                title="\u2302 Room Created",
                border_style="oikos.border",
                box=box.ROUNDED,
                padding=(0, 2),
            )
        )
    except ValueError as e:

        console.print(
            Panel(str(e), title="\u26a0 Error", border_style="oikos.error", box=box.HEAVY, padding=(0, 2))
        )
        raise SystemExit(1)


@room.command("switch")
@click.argument("room_id")
def room_switch(room_id: str):
    """Switch the active room (closes current session)."""
    from core.rooms.manager import get_room_manager

    mgr = get_room_manager()
    try:
        current = mgr.get_active_room()

        console.print(
            Panel(
                "Session saved.",
                title=f"\u2302 Closing: {current.name}",
                border_style="oikos.dim",
                box=box.ROUNDED,
                padding=(0, 2),
            )
        )
        console.print("[oikos.dim]         \u25c8[/]")
        time.sleep(0.3)

        new_room = mgr.switch_room(room_id)

        details = []
        if new_room.vault_scope.mode != "all":
            paths = ", ".join(new_room.vault_scope.paths)
            details.append(f"Vault: {new_room.vault_scope.mode}{': ' + paths if paths else ''}")
        if new_room.toolsets:
            details.append(f"Tools: {', '.join(new_room.toolsets)}")
        if new_room.model.model:
            details.append(f"Model: {new_room.model.model}")
        body = "\n".join(details) if details else "Default configuration"

        console.print(
            Panel(
                body,
                title=f"\u2302 Entering: {new_room.name}",
                border_style="oikos.bright",
                box=box.ROUNDED,
                padding=(0, 2),
            )
        )
    except ValueError as e:
        console.print(
            Panel(
                str(e),
                title="\u26a0 Error",
                border_style="oikos.error",
                box=box.HEAVY,
                padding=(0, 2),
            )
        )
        raise SystemExit(1)


@room.command("delete")
@click.argument("room_id")
@click.option("--yes", is_flag=True, help="Skip confirmation")
def room_delete(room_id: str, yes: bool):
    """Delete a room (requires --yes)."""
    from core.rooms.manager import get_room_manager

    if not yes:
        console.print("[yellow]Use --yes to confirm deletion.[/]")
        return
    mgr = get_room_manager()
    try:
        mgr.delete_room(room_id)
        console.print(f"  Room [bold]{room_id}[/] deleted.")
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        raise SystemExit(1)


@room.command("edit")
@click.argument("room_id")
@click.option("--name", default=None, help="New display name")
@click.option("--description", default=None, help="New description")
@click.option("--add-toolset", multiple=True, help="Add a toolset")
@click.option("--remove-toolset", multiple=True, help="Remove a toolset")
@click.option("--temperature", default=None, type=float, help="Generation temperature (0.0-2.0)")
@click.option("--max-tokens", default=None, type=int, help="Max response tokens (256-32768)")
def room_edit(room_id: str, name: str | None, description: str | None, add_toolset: tuple, remove_toolset: tuple, temperature: float | None, max_tokens: int | None):
    """Edit a room's configuration."""
    from core.rooms.manager import get_room_manager

    mgr = get_room_manager()
    try:
        existing = mgr.get_room(room_id)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        raise SystemExit(1)

    updates: dict = {}
    if name is not None:
        updates["name"] = name
    if description is not None:
        updates["description"] = description

    if add_toolset or remove_toolset:
        current = set(existing.toolsets) if existing.toolsets else set()
        current |= set(add_toolset)
        current -= set(remove_toolset)
        updates["toolsets"] = sorted(current) if current else None

    if temperature is not None:
        if not 0.0 <= temperature <= 2.0:
            console.print("[red]Temperature must be between 0.0 and 2.0[/]")
            raise SystemExit(1)
        updates["voice"] = {**(existing.voice.model_dump()), "temperature": temperature}

    if max_tokens is not None:
        if not 256 <= max_tokens <= 32768:
            console.print("[red]Max tokens must be between 256 and 32768[/]")
            raise SystemExit(1)
        updates["limits"] = {**(existing.limits.model_dump()), "max_tokens_per_query": max_tokens}

    if not updates:
        console.print("[yellow]No changes specified.[/]")
        return

    try:
        mgr.update_room(room_id, updates)
        console.print(f"  Room [bold]{room_id}[/] updated.")
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        raise SystemExit(1)


@room.command("export")
@click.argument("room_id")
def room_export(room_id: str):
    """Export a room config as JSON to stdout."""
    from core.rooms.manager import get_room_manager

    mgr = get_room_manager()
    try:
        r = mgr.get_room(room_id)
        click.echo(r.model_dump_json(indent=2))
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        raise SystemExit(1)


@room.command("import")
@click.argument("path", type=click.Path(exists=True))
def room_import(path: str):
    """Import a room from a JSON file."""
    import json
    from pathlib import Path

    from core.rooms.manager import get_room_manager
    from core.rooms.models import RoomConfig

    mgr = get_room_manager()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        config = RoomConfig.model_validate(data)
        mgr.create_room(config)
        console.print(f"  Room [bold]{config.id}[/] imported.")
    except (ValueError, json.JSONDecodeError) as e:
        console.print(f"[red]{e}[/]")
        raise SystemExit(1)


@room.command("_default", hidden=True)
@click.argument("room_name")
def room_switch_shorthand(room_name):
    """Switch to a room by name (shorthand)."""
    from core.rooms.manager import get_room_manager

    mgr = get_room_manager()
    available = [r.id for r in mgr.list_rooms()]
    if room_name not in available:
        console.print(
            f"[oikos.error]No room named '{room_name}'. "
            f"Available: {', '.join(available)}.[/]"
        )
        raise SystemExit(1)
    mgr.switch_room(room_name)
    r = mgr.get_active_room()
    console.print(f"[oikos.success]◈ Switched to {r.name}[/] [dim]({r.id})[/]")


@main.command("approvals")
def approvals_list():
    """List pending approval requests."""
    import httpx

    from core.interface.settings import get_setting

    try:
        resp = httpx.get(f"http://127.0.0.1:{get_setting('api_port')}/api/approvals", timeout=5)
        pending = resp.json().get("pending", [])
    except httpx.ConnectError:
        console.print("[#FF3333]Server not running. Start with: oikos serve[/]")
        raise SystemExit(1)

    if not pending:
        console.print("[#6B5012]No pending approvals.[/]")
        return

    from rich.table import Table

    table = Table(show_lines=False, box=None, padding=(0, 2))
    table.add_column("ID", style="#6B5012", width=10)
    table.add_column("Tool", style="#D4A017")
    table.add_column("Action", style="#FFB000")
    table.add_column("Room", style="#6B5012")
    for p in pending:
        table.add_row(p.get("id", "?"), p.get("tool_name", "?"), p.get("action", "?"), p.get("room", "default") or "default")

    console.print(table)
    console.print(
        f"\n[#6B5012]{len(pending)} pending. "
        f"Use [#D4A017]oikos approve <id>[/] or [#D4A017]oikos reject <id>[/].[/]"
    )


@main.command("approve")
@click.argument("proposal_id")
def approve_cmd(proposal_id: str):
    """Approve a pending action by proposal ID."""
    import httpx

    from core.interface.settings import get_setting

    try:
        resp = httpx.post(f"http://127.0.0.1:{get_setting('api_port')}/api/approvals/{proposal_id}/approve", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            console.print(f"[#33FF33]\u2713[/] Approved: {data.get('action', data.get('tool_name', proposal_id))}")
            return
        elif resp.status_code == 404:
            console.print(f"[#FF3333]Proposal {proposal_id!r} not found.[/]")
            raise SystemExit(1)
        elif resp.status_code == 409:
            console.print(f"[#FF3333]{resp.json().get('detail', 'Already resolved')}[/]")
            raise SystemExit(1)
        else:
            console.print(f"[#FF3333]Server error: {resp.status_code}[/]")
            raise SystemExit(1)
    except httpx.ConnectError:
        console.print("[#FF3333]Server not running. Start with: oikos serve[/]")
        raise SystemExit(1)


@main.command("reject")
@click.argument("proposal_id")
@click.option("--reason", "-r", default=None, help="Rejection reason")
def reject_cmd(proposal_id: str, reason: str | None):
    """Reject a pending action by proposal ID."""
    import httpx

    from core.interface.settings import get_setting

    try:
        body = {"reason": reason} if reason else None
        resp = httpx.post(f"http://127.0.0.1:{get_setting('api_port')}/api/approvals/{proposal_id}/reject", json=body, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            console.print(f"[#FF3333]\u2717[/] Rejected: {data.get('action', data.get('tool_name', proposal_id))}")
            return
        elif resp.status_code == 404:
            console.print(f"[#FF3333]Proposal {proposal_id!r} not found.[/]")
            raise SystemExit(1)
        elif resp.status_code == 409:
            console.print(f"[#FF3333]{resp.json().get('detail', 'Already resolved')}[/]")
            raise SystemExit(1)
        else:
            console.print(f"[#FF3333]Server error: {resp.status_code}[/]")
            raise SystemExit(1)
    except httpx.ConnectError:
        console.print("[#FF3333]Server not running. Start with: oikos serve[/]")
        raise SystemExit(1)


@main.command()
def setup():
    """Interactive onboarding — configure name, model, and providers."""
    from core.onboarding.state import is_onboarding_complete, mark_onboarding_complete

    if is_onboarding_complete():
        console.print("[green]oikOS is already set up.[/]")
        if not click.confirm("Run setup again?", default=False):
            return
        console.print()

    console.print("[bold]Welcome to oikOS.[/]\n")

    # Step 1: Identity
    name = click.prompt("What should your AI call you?")
    from core.onboarding.identity import bootstrap_identity

    try:
        bootstrap_identity(name)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        return

    # Step 2: Backend detection
    console.print("\n[dim]Scanning for local backends...[/]")
    from core.onboarding.detector import detect_backends

    backends = detect_backends()
    if backends:
        for b in backends:
            models = ", ".join(m["name"] for m in b["models"][:3])
            console.print(f"  [green]Found {b['backend']}[/] at localhost:{b['port']} — {models}")
    else:
        console.print("  [yellow]No local backends detected.[/]")
        console.print("  [dim]Install Ollama: https://ollama.com[/]")

    # Step 3: Model selection
    if backends:
        all_models = [(b["backend"], m["name"]) for b in backends for m in b["models"]]
        if all_models:
            default_provider, default_model = all_models[0]
            model = click.prompt("Select default model", default=default_model)
            from core.onboarding.manager import save_model_selection

            save_model_selection(default_provider, model)

    # Step 4: Cloud (optional)
    if click.confirm("\nConfigure cloud providers?", default=False):
        console.print("[dim]Add API keys in the web wizard: oikos serve → http://localhost:8420[/]")

    # Complete
    from core.onboarding.manager import write_providers_toml

    write_providers_toml()
    mark_onboarding_complete()
    console.print("\n[green bold]Setup complete.[/] Run [bold]oikos serve[/] to start.")


# ── Task 3: oikos ask (alias for query) ─────────────────────────────


@main.command()
@click.argument("query")
@click.option("--local-only", is_flag=True, help="Force local inference regardless of confidence")
@click.option("--cloud", is_flag=True, help="Force cloud inference (bypasses confidence routing)")
@click.option("--provider", type=str, default=None, help="Provider name (e.g., local, claude, openai)")
@click.option("--model", type=str, default=None, help="Model override (e.g., gpt-4o, qwen2.5:7b)")
@click.option("--no-scrub", is_flag=True, help="Skip PII detection/scrubbing")
@click.option("--no-stream", is_flag=True, help="Disable streaming (blocking mode)")
@click.option("--debug", is_flag=True, help="Show routing cascade diagnostics")
@click.option("-y", "--yes", is_flag=True, help="Auto-accept response (no prompt)")
@click.pass_context
def ask(ctx, **kwargs):
    """Alias for 'query' — run a query through the handler pipeline."""
    ctx.invoke(query, **kwargs)


# ── Task 3: oikos vault ─────────────────────────────────────────────


@main.group(invoke_without_command=True)
@click.argument("query_text", required=False, default=None)
@click.pass_context
def vault(ctx, query_text):
    """Browse or search the vault. Pass a query to search."""
    if ctx.invoked_subcommand is not None:
        return

    if query_text:
        ctx.invoke(search, query=query_text)
        return

    from core.interface.config import PROJECT_ROOT

    vault_dir = PROJECT_ROOT / "vault"
    if not vault_dir.exists():
        console.print("[red]Vault directory not found.[/]")
        raise SystemExit(1)

    table = Table(show_header=True, header_style="oikos.header", show_lines=False)
    table.add_column("Directory", style="oikos.primary")
    table.add_column("Files", style="dim", justify="right")

    for sub in sorted(vault_dir.iterdir()):
        if sub.is_dir() and not sub.name.startswith("."):
            md_count = len(list(sub.glob("*.md")))
            table.add_row(sub.name, str(md_count))

    console.print(Panel(table, title="◈ Vault", box=box.ROUNDED, border_style="oikos.border"))


# ── Task 4: oikos health ────────────────────────────────────────────


def _check_daemon() -> bool:
    from core.interface.config import DAEMON_PID_FILE

    return DAEMON_PID_FILE.exists()


def _check_api() -> bool:
    try:
        import httpx
        from core.interface.settings import get_setting

        resp = httpx.get(f"http://localhost:{get_setting('api_port')}/api/system/state", timeout=0.5)
        return resp.status_code == 200
    except Exception:
        return False


def _check_ollama() -> bool:
    try:
        import httpx

        resp = httpx.get("http://localhost:11434/api/tags", timeout=1.0)
        return resp.status_code == 200
    except Exception:
        return False


def _check_vault_index() -> bool:
    from core.interface.config import PROJECT_ROOT

    index_dir = PROJECT_ROOT / "vault" / ".lancedb"
    return index_dir.exists()


@main.command()
def health():
    """System health check — daemon, API, Ollama, vault index."""
    checks = [
        ("Daemon", _check_daemon()),
        ("API Server", _check_api()),
        ("Ollama", _check_ollama()),
        ("Vault Index", _check_vault_index()),
    ]

    table = Table(show_header=True, header_style="oikos.header", show_lines=False)
    table.add_column("Component", style="oikos.primary")
    table.add_column("Status", justify="center")

    for name, ok in checks:
        icon = "[green]✓[/]" if ok else "[red]✗[/]"
        table.add_row(name, icon)

    console.print(Panel(table, title="◈ Health", box=box.ROUNDED, border_style="oikos.border"))


# ── Task 5: oikos agents ────────────────────────────────────────────


@main.command()
def agents():
    """List registered agents and their status."""
    daemon_active = _check_daemon()

    table = Table(show_header=True, header_style="oikos.header", show_lines=False)
    table.add_column("Agent", style="oikos.primary")
    table.add_column("Status")

    table.add_row("Daemon", "[green]active[/]" if daemon_active else "[red]stopped[/]")
    table.add_row("KAIROS", "[dim]idle[/]")

    console.print(Panel(table, title="◈ Agents", box=box.ROUNDED, border_style="oikos.border"))


# ── Task 5: oikos tools ─────────────────────────────────────────────

TOOLSET_INFO = {
    "vault": (5, "search, compile, index, ingest, stats"),
    "system": (16, "status, state, config, daemon, gauntlet, exec, inference..."),
    "file": (8, "read, list, search, write, edit..."),
    "browser": (6, "fetch, search, extract, screenshot..."),
    "research": (5, "queue, run, review, approve, reject"),
    "git": (2, "status, log"),
    "oracle": (1, "oracle status"),
    "google": (8, "gmail, calendar, drive services"),
}


@main.command()
def tools():
    """List active MCP toolsets for the current room."""
    from core.rooms.manager import RoomManager

    mgr = RoomManager()
    room = mgr.get_active_room()
    active_toolsets = room.toolsets or list(TOOLSET_INFO.keys())

    table = Table(show_header=True, header_style="oikos.header", show_lines=False)
    table.add_column("Toolset", style="oikos.primary")
    table.add_column("Tools", justify="right", style="dim")
    table.add_column("Description")

    for ts in active_toolsets:
        count, desc = TOOLSET_INFO.get(ts, (0, "unknown"))
        table.add_row(ts, str(count), desc)

    console.print(Panel(table, title=f"◈ Tools ({room.name})", box=box.ROUNDED, border_style="oikos.border"))


# ── Task 5: oikos history ───────────────────────────────────────────

SESSIONS_DIR = None  # patched in tests; falls back to config


def _get_sessions_dir():
    if SESSIONS_DIR is not None:
        return SESSIONS_DIR
    from core.interface.config import PROJECT_ROOT

    return PROJECT_ROOT / "logs" / "sessions"


@main.command()
def history():
    """Show recent session history."""
    sessions_dir = _get_sessions_dir()
    if not sessions_dir.exists():
        console.print("[yellow]No session history found.[/]")
        return

    dirs = sorted(
        [d for d in sessions_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )[:10]

    if not dirs:
        console.print("[yellow]No sessions recorded.[/]")
        return

    table = Table(show_header=True, header_style="oikos.header", show_lines=False)
    table.add_column("Date", style="oikos.primary")
    table.add_column("Files", style="dim", justify="right")

    for d in dirs:
        file_count = len(list(d.iterdir()))
        table.add_row(d.name, str(file_count))

    console.print(Panel(table, title="◈ Sessions", box=box.ROUNDED, border_style="oikos.border"))


# ── Task 6: oikos config ────────────────────────────────────────────

CONFIG_REDIRECTS = {
    "default_provider": "oikos provider <name>",
    "cloud_provider": "oikos provider <name>",
}

CONFIG_REDIRECT_PREFIXES = [
    ("provider_", "oikos provider <name>"),
    ("room.", "oikos room edit <name>"),
    ("allowed_providers", "oikos room edit <name>"),
]


@main.command("config")
@click.argument("key", required=False, default=None)
@click.argument("value", required=False, default=None)
def config_cmd(key, value):
    """View or update runtime settings."""
    from core.interface.settings import get_setting, get_tiered_settings, update_setting
    from core.interface.settings_registry import SETTINGS_REGISTRY, SettingTier

    # Bare: tiered display
    if key is None:
        tiered = get_tiered_settings()
        tier_labels = {
            "essential": "Essential",
            "advanced": "Advanced [dim](use TUI Settings F5 or API)[/]",
            "expert": "Expert [dim](edit settings.json directly)[/]",
        }
        for tier_name, label in tier_labels.items():
            settings = tiered.get(tier_name, {})
            if not settings:
                continue
            console.print(f"\n  [bold]{label}[/]")
            for skey, meta in sorted(settings.items()):
                val = meta.get("value", "")
                desc = meta.get("description", "")
                console.print(f"    {skey:<30} {str(val):<12} [dim]{desc}[/]")
        console.print()
        return

    # Key only: show single value (any tier)
    if value is None:
        try:
            val = get_setting(key)
            defn = SETTINGS_REGISTRY.get(key)
            desc = f"  [dim]{defn.description}[/]" if defn else ""
            console.print(f"  {key} = {val}{desc}")
        except KeyError:
            console.print(f"[red]Unknown setting: {key}[/]")
            raise SystemExit(1)
        return

    # Key + value: check redirects first
    if key in CONFIG_REDIRECTS:
        console.print(f"[yellow]Use: {CONFIG_REDIRECTS[key]}[/]")
        return

    for prefix, redirect in CONFIG_REDIRECT_PREFIXES:
        if key.startswith(prefix):
            console.print(f"[yellow]Use: {redirect}[/]")
            return

    # Registry lookup
    defn = SETTINGS_REGISTRY.get(key)
    if defn is None:
        console.print(f"[red]Unknown setting: {key}[/]")
        raise SystemExit(1)

    # Advanced tier: redirect to TUI/API
    if defn.tier == SettingTier.ADVANCED:
        console.print(f"[yellow]Advanced setting. Use TUI Settings (F5) or the API.[/]")
        return

    # Essential and Expert: write directly
    try:
        result = update_setting(key, value)
    except (ValueError, KeyError) as e:
        console.print(f"[red]{e}[/]")
        raise SystemExit(1)

    console.print(f"  {key} = {value} [green](saved)[/]")
    if result.get("restart_required"):
        console.print(f"  [yellow]Restart required for this change to take effect.[/]")


if __name__ == "__main__":
    main()
