"""OIKOS CLI — index, search, compile, query, credits, status."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time

import click
from rich.console import Console
from rich.table import Table

# Force UTF-8 on Windows to avoid cp1252 encoding errors with unicode content
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

console = Console(force_terminal=True)


_BANNER = r"""
        ██  ██   ██  ██████  ███████
  ██████ ██ ██  ██  ██    ██ ██
 ██    ██ ██ █████   ██    ██ ███████
 ██    ██ ██ ██  ██  ██    ██      ██
  ██████  ██ ██   ██  ██████  ███████
           The OS for your AI.
"""


@click.group(invoke_without_command=True)
@click.option("--prod", is_flag=True, help="Production mode (serve frontend from dist/)")
@click.pass_context
def main(ctx, prod):
    """OIKOS_OMEGA — Sovereign Memory Retrieval Layer."""
    if ctx.invoked_subcommand is not None:
        return
    _boot(prod=prod)


def _boot(prod: bool = False) -> None:
    """Boot the full OIKOS stack: Ollama + API server + frontend."""
    import atexit
    import time
    import webbrowser

    import httpx

    console.print(f"[bold amber]{_BANNER}[/]")
    console.print("[bold]oikOS — Booting...[/]\n")

    # 1. Ollama
    _ensure_ollama()

    children: list[subprocess.Popen] = []

    def _cleanup():
        for p in children:
            try:
                p.terminate()
            except OSError:
                pass

    atexit.register(_cleanup)

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    if prod:
        # Production: build frontend if needed, serve everything from one process
        dist_dir = os.path.join(project_root, "frontend", "dist")
        if not os.path.isdir(dist_dir):
            console.print("[dim]Building frontend...[/]")
            subprocess.run(
                ["npm", "run", "build"],
                cwd=os.path.join(project_root, "frontend"),
                check=True,
                shell=True,
            )
            console.print("[green]Frontend built.[/]")

        console.print("[bold]Starting API server (prod) on 127.0.0.1:8420[/]")
        url = "http://localhost:8420"
    else:
        # Dev: start API server in background, then frontend dev server
        console.print("[dim]Starting API server (dev) on 127.0.0.1:8420...[/]")
        api_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "core.interface.api.server:app_dev", "--host", "127.0.0.1", "--port", "8420", "--log-level", "warning"],
            cwd=project_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        children.append(api_proc)

        # Wait for API to be ready
        for _ in range(15):
            try:
                httpx.get("http://127.0.0.1:8420/api/health", timeout=2)
                break
            except (httpx.ConnectError, httpx.TimeoutException):
                time.sleep(1)

        console.print("[green]API server ready.[/]")

        console.print("[dim]Starting frontend dev server on localhost:5173...[/]")
        fe_proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=os.path.join(project_root, "frontend"),
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        children.append(fe_proc)

        # Wait for Vite to be ready
        for _ in range(10):
            try:
                httpx.get("http://localhost:5173", timeout=2)
                break
            except (httpx.ConnectError, httpx.TimeoutException):
                time.sleep(1)
        console.print("[green]Frontend ready.[/]")
        url = "http://localhost:5173"

    console.print(f"\n[bold green]OIKOS ONLINE[/] → {url}")
    console.print("[dim]Press Ctrl+C to shut down.[/]\n")
    webbrowser.open(url)

    if prod:
        # In prod mode, run the server in-process (blocking)
        from core.interface.api.server import run_server
        try:
            run_server(port=8420, dev=False)
        except KeyboardInterrupt:
            pass
    else:
        # In dev mode, wait for children and forward Ctrl+C
        try:
            for p in children:
                p.wait()
        except KeyboardInterrupt:
            console.print("\n[bold]Shutting down...[/]")
            _cleanup()
            console.print("[dim]OIKOS offline.[/]")


@main.command()
@click.option("--full", is_flag=True, help="Full rebuild (drop + re-index all)")
def index(full: bool):
    """Index vault markdown files into LanceDB."""
    from core.memory.embedder import check_health

    if not check_health():
        console.print(
            "[bold red]Ollama unreachable or embedding model not found.[/]\n"
            "Install: https://ollama.com\n"
            "Then: ollama pull nomic-embed-text:v1.5",
        )
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

    table = Table(title=f"Search: {query!r}", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Score", width=6)
    table.add_column("Tier", width=10)
    table.add_column("Source", width=30)
    table.add_column("Header", width=25)
    table.add_column("Preview", width=50)

    for i, r in enumerate(results, 1):
        preview = r.content[:120].replace("\n", " ")
        table.add_row(
            str(i),
            f"{r.final_score:.3f}",
            r.tier.value,
            r.source_path,
            r.header_path,
            preview,
        )

    console.print(table)


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
        from core.cognition.handler import execute_query

        console.print("[dim]Processing query...[/]")
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

        console.print("[dim]Streaming...[/]")
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
    import subprocess
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
    import subprocess
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

    table = Table(title="Gauntlet Results", show_lines=True)
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

    console.print(table)
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
    from rich.panel import Panel

    blips = []
    nudges = []

    try:
        from core.autonomic.scanner import load_undelivered_blips, mark_blips_delivered
        blips = load_undelivered_blips()
    except Exception:
        pass

    try:
        from core.autonomic.drift import generate_nudges
        nudges = generate_nudges()
    except Exception:
        pass

    proposals = []
    try:
        from core.agency.consolidation import load_pending_proposals, mark_proposal_status
        proposals = load_pending_proposals()
    except Exception:
        pass

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
        except Exception:
            pass

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
    except Exception:
        pass

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
def serve(port: int, dev: bool):
    """Start the OIKOS API server."""
    from core.interface.api.server import run_server

    mode = "dev" if dev else "prod"
    console.print(f"[bold]Starting API server[/] ({mode}) on 127.0.0.1:{port}")
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
def status():
    """Show Ollama health, index stats, and handler subsystems."""
    from core.memory.embedder import check_health
    from core.memory.indexer import get_table_stats

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

    # Cloud bridge (Phase 6a)
    import os
    from core.interface.config import CLOUD_MODEL, CLOUD_HARD_CEILING_MULTIPLIER
    cloud_key = bool(os.environ.get("GEMINI_API_KEY"))
    cloud_str = f"[green]ACTIVE ({CLOUD_MODEL})[/]" if cloud_key else "[yellow]NO API KEY[/]"
    console.print(f"Cloud Bridge: {cloud_str}")
    hard_ceiling = bal.monthly_cap * CLOUD_HARD_CEILING_MULTIPLIER
    ceiling_remaining = hard_ceiling - bal.used
    ceiling_str = f"[green]{ceiling_remaining:.0f}[/]" if ceiling_remaining > 0 else "[bold red]BREACHED[/]"
    console.print(f"Hard Ceiling: {ceiling_str} remaining (ceiling={hard_ceiling:.0f})")

    # Drift detector diagnostic + nudges (Phase 5.7)
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
    except Exception:
        pass  # Drift detector is best-effort

    # FSM state (Phase 6b)
    try:
        from core.autonomic.fsm import get_current_state, get_last_transition_time

        fsm_state = get_current_state()
        fsm_colors = {"active": "green", "idle": "yellow", "asleep": "dim"}
        fsm_color = fsm_colors.get(fsm_state.value, "white")
        last_ts = get_last_transition_time()
        ts_str = f" (since {last_ts[:19]})" if last_ts else ""
        console.print(f"FSM State:    [{fsm_color}]{fsm_state.value.upper()}[/]{ts_str}")
    except Exception:
        pass

    # Scanner status (Phase 6b)
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
    except Exception:
        pass


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
    console.print(f"VRAM Yielded: {'YES' if status['vram_yielded'] else 'no'}")
    console.print(f"Health Fails: {status['health_failures']}")


@main.command("vault-check")
def vault_check():
    """Scan vault files for stale frontmatter dates and missing metadata."""
    from core.calibration import vault_freshness

    report = vault_freshness.run(console=console)
    if report["stale"] == 0 and report["missing_frontmatter"] == 0:
        console.print("[green]All vault files current.[/]")


@main.command("sync-check")
def sync_check():
    """Check sync manifest for drifted cross-platform files."""
    from core.calibration import sync_manifest

    sync_manifest.run(console=console)


@main.group()
def provider():
    """Manage inference providers."""
    pass


@provider.command("list")
def provider_list():
    """List all registered providers and their availability."""
    from core.cognition.handler import get_provider_registry
    reg = get_provider_registry()
    for name in reg.list_all():
        p = reg.get(name)
        status = "[green]AVAILABLE[/]" if p.is_available() else "[red]UNAVAILABLE[/]"
        default = " [bold](default)[/]" if name == reg.get_default_name() else ""
        console.print(f"  {name}: {status}{default}")


@provider.command("test")
def provider_test():
    """Test connectivity to all configured providers."""
    from core.cognition.handler import get_provider_registry
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

    from core.cognition.handler import get_provider_registry
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
        from core.cognition.handler import get_provider_registry
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


if __name__ == "__main__":
    main()
