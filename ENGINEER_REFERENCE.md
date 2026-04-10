# ENGINEER Reference — Tier 2 (loaded on demand)

This file contains toolkit documentation, codebase structure, CLI commands, and other reference data not needed at session start.

---

## TOOLKIT (detailed)

- **Python 3.12+**: Primary language.
- **Ollama**: Local inference (qwen2.5:14b primary, qwen2.5:7b fallback).
- **LanceDB**: Vector memory (embedded, serverless).
- **Rich**: Terminal UI.
- **Pytest + Vitest**: Verification (Python + frontend).
- **httpx**: Async HTTP for cloud providers.
- **anthropic**: Anthropic SDK for Claude API.
- **google-genai**: Google Gemini SDK.
- **FastAPI**: API server + WebSocket.
- **Docker**: `docker compose up` starts 3 containers (oikos-core + ollama + searxng).

---

## CODEBASE STRUCTURE

```
core/
+-- auth/            claude_discovery, claude_headers, claude_provider, google_oauth, refresh, google_services (gmail, calendar, drive)
+-- cognition/       handler (thin orchestrator), inference, complexity, routing, cloud, compiler
|   +-- pipeline/    classify, context, route, dispatch, postprocess, trace
|   +-- providers/   protocol, registry, router, bootstrap, ollama/anthropic/gemini/openai/litellm, content_classifier, config_loader, cost_tracker
+-- memory/          search, indexer, chunker, embedder, session
+-- identity/        coherence, contradiction, assertions, input_guard
+-- safety/          pii, output_filter, sensitivity, credits
+-- autonomic/       fsm, scanner, drift, confidence, calibration, daemon, notifications
+-- interface/       cli, models, config, theme, boot, info, api/ (FastAPI routes + WS), tui/ (Textual TUI)
+-- agency/          consolidation, eval, adversarial, rpg, autonomy, approval, file_agent, context_engine, compressor, budget, planner
|   +-- browser/     Playwright browser tools (6 tools)
|   +-- research/    IDLE research tools (5 tools)
+-- rooms/           models, manager, defaults, limits
+-- onboarding/      detector, state, identity, manager
+-- framework/       @oikos_tool decorator, OikosServer, middleware/ (7 layers), tools/ (50 tools across 8 toolsets)
```

---

## oikOS CLI COMMANDS

| Command | Description |
|---|---|
| `oikos query` | Send a query through the full inference pipeline |
| `oikos search` | Hybrid vault search (BM25 + vector) |
| `oikos compile` | Assemble context window from vault |
| `oikos index [--full]` | Rebuild vault index (incremental or full) |
| `oikos serve [--dev]` | Start FastAPI server |
| `oikos provider` | Manage inference providers |
| `oikos daemon` | Start/stop background daemon |
| `oikos gauntlet` | Run adversarial security probes |
| `oikos evaluate` | Run eval harness |
| `oikos calibrate` | Accuracy-at-confidence curve |
| `oikos status` | System status overview |
| `oikos credits` | Query budget tracker |
| `oikos session` | Session management |
| `oikos state` | FSM state display |
| `oikos idle/wake/sleep` | State transitions |
| `oikos promote` | Review memory promotion proposals |
| `oikos consolidate` | Memory consolidation |
| `oikos vault-check` | Scan vault for stale/missing metadata |
| `oikos sync-check` | Cross-platform drift detection |
| `oikos test` | Run test suite |

---

## WINDOWS COMPATIBILITY — CODE PATTERNS

### NEVER use without `sys.platform` guard:
- `os.kill(pid, signal)` — On Windows, signal 0 sends `CTRL_C_EVENT`. `SIGTERM` calls `TerminateProcess`.
- `os.fork()`, `os.setsid()`, `os.getuid()`, `os.killpg()` — Unix-only, raise `AttributeError`.
- `signal.SIGKILL`, `signal.SIGUSR1`, `signal.SIGHUP`, `signal.SIGQUIT` — Do not exist on Windows.

### Windows process patterns:
```python
# Check if process exists (cross-platform)
import ctypes
kernel32 = ctypes.windll.kernel32
handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
if handle:
    kernel32.CloseHandle(handle)

# Graceful stop on Windows (daemon uses SIGBREAK handler)
if sys.platform == "win32":
    os.kill(pid, signal.CTRL_BREAK_EVENT)
else:
    os.kill(pid, signal.SIGTERM)

# Background subprocess without console window
subprocess.Popen(cmd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
```

### Enforcement:
- **Semgrep**: `.semgrep/windows_compat.yaml` — 3 rules
- **Pre-commit**: `.pre-commit-config.yaml` — AST walker
- **Claude Code hook**: `.claude/hooks/platform_guard.py` — blocks `Edit`/`Write` containing unguarded patterns

---

## BRAND CONVENTION

- **Public-facing:** oikOS (camel-case). UI, CLI, marketing, GitHub, docs.
- **Internal/codebase:** OIKOS OMEGA. Vault files, variable names, internal docs.
- **Tagline:** "The home for AI agents."
- **Design:** Phosphor Standard — amber CRT, 3 community themes (amber/green/white).
- **Logo:** Finalized v1.1 — pixel-grid house mark + ansi_shadow wordmark. Spec: `OIKOS_LOGO_SPEC_v1_1.md`.
- **Domain:** oikos-os.com (DEPLOYED)
- **GitHub:** github.com/oikos-os/oikOS
- **X accounts:** @oikOS_os (product)
- **Never expose:** operator identity markers or cross-project references

---

## FOUNDING DOCTRINE (summary)

Mission Hierarchy: Layer 1 (AIOS) -> Layer 2 (KAIROS) -> Layer 3 (Own LLM) -> Layer 4 (Home OS) -> Layer 5 (Embodiment) -> Layer 6 (Beyond).

Key principles: Local-first, open formats, via negativa, barbell strategy, fiduciary duty, exit guarantee, requisite variety.

Three-lens test: (1) Stoicism — inner citadel, dichotomy of control. (2) Cybernetics — feedback loop, user override. (3) Antifragility — more robust or new fragility?

Full document lives in your operator vault; see `vault/identity/` for tracked fragments.

---

## CHRONICLER PATTERN

Division leads use oikOS as a context engine via Claude Code + project CLAUDE.md + `oikos search`/`oikos compile`. ENGINEER maintains infrastructure; division leads consume it.

---

## SOVEREIGN VAULT BOUNDARY

SOVEREIGN has no write access to OIKOS_OMEGA. All vault content from SOVEREIGN flows through: staging -> ENGINEER review -> placement -> index -> gauntlet -> report.

Origin: 2026-03-07 incident where direct vault modifications deleted 23 files and broke tests.
