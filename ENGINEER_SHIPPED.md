# ENGINEER — What Shipped

Everything below is merged to `master` and passing. This is Tier 3 history — not loaded at session start.

---

### Phase 7d: Bounded Agency (COMPLETE)
- **Module 1: Context Engine Core** — observation masking, tool compression, token budget, ReWOO planner. 81 tests.
- **Module 2: Autonomy Matrix** — SAFE/ASK_FIRST/PROHIBITED classification, ApprovalQueue, FastAPI endpoints. 61 tests.
- **Module 3: File Management Agent** — scope validation, read/write/move/search, vault delegation. 36 tests.
- **T-037: Multi-Provider Inference** — InferenceProvider Protocol, ProviderRegistry, PrivacyAwareRouter, ContentClassifier, 4 providers. ~101 tests.
- **T-038: Codebase Review** — 2 CRITICAL + 8 HIGH fixed. 10 MEDIUM + 9 LOW documented.

### T-047: Multi-Provider Strategy (COMPLETE)
`providers.toml` config, dedicated OpenAI provider (httpx), bootstrap refactor (TOML-first, env fallback), `--provider`/`--model` CLI flags, OPT-01 adaptive model selection (SIMPLE->7b, MODERATE->14b, COMPLEX->cloud), OPT-06 per-query cost tracking (JSONL). 36 tests.

### Phase 7e Module 0: Agent Framework (COMPLETE)
`@oikos_tool` decorator, OikosServer (composes FastMCP), 6-layer middleware chain (auth->privacy->autonomy->rate limit->cost->audit). Privacy + audit are mandatory and cannot be removed. NEVER_LEAVE blocks all remote transports. 65 tests. Located at `core/framework/`.

### Phase 7e Module 1: Core MCP Tools (COMPLETE)
16 -> 30 MCP tools registered. Vault (5), System (12), File (8), Git (2), Oracle (1), Inference (2). Tool names use underscores for Claude Desktop compatibility. ASK_FIRST tools return descriptive approval prompts. T-056 filesystem scope expansion applied. T-057 code reviewed: 2 CRITICAL + 3 HIGH + 2 MEDIUM found and fixed. Total: 42 tools across 7 toolsets.

### Phase 7e Module 2: Browser Tools (COMPLETE)
6 browser tools (Playwright + SearXNG). 47 tests. 2 CRITICAL found in code review (SSRF, async crash) and fixed.

### Phase 7e Module 3: IDLE Research (COMPLETE)
5 research tools. 41 tests. 2 CRITICAL found in code review (path traversal) and fixed.

### Phase 7e Module 4: Docker Compose (COMPLETE)
3 containers: oikos-core + ollama + searxng. 22 tests. Phase 7e CERTIFIED. ChromaDB dropped (via negativa).

### Phase A: The Phosphor Aesthetic (COMPLETE)
Amber CRT terminal world. Rich theme system (11 tokens), pyfiglet ASCII banner, boot sequence, CRT scanlines + flicker + vignette, phosphor text glow, self-hosted fonts, accessibility toggle. 11 new tests.

### Phase B: The World (COMPLETE)
Room switch transitions, thinking indicators, warm amber backgrounds, panel borders, breathing glow, `oikos info` color bars + room list.

### Phase C: The Identity (COMPLETE -- aesthetic lock)
Community themes (amber/green/white) for CLI + web, `oikos info` polish, boot quote rotation, branded error states, branded help, VHS tape recording script. **Aesthetic locked.**

### T-071: OAuth Integration (O1-O4 COMPLETE)
Claude Code credential discovery + token refresh, identity headers, 4 API endpoints, Google OAuth 2.0 flow. 42 OAuth tests. 5 CRITICAL security fixes.

### v1.9.1: Audit Cleanup (COMPLETE)
229 findings, 85 resolved, 0 CRITICALs remaining. 19 security tests added. Git filter-repo: 488 commits rewritten.

### DQ-005: Model Switching UX + Google Services (COMPLETE)
T-081 (per-Room model defaults), T-082 (OAuth O5, Google services, 8 tools), T-083 (content classifier scope fix). Total: 51 MCP tools across 8 toolsets.

### OAuth Inference + T-084 O6 (COMPLETE)
Claude API via OAuth at zero cost. Per-Room `allowed_providers`. OAuth O1-O6 complete.

### Textual TUI: The Living Room (COMPLETE -- TUI-1/2/3/4)
7 screens, ContentSwitcher architecture, SSE streaming, 539-line TCSS phosphor theme. 65 tests.

### T-085: Hardening Sprint (COMPLETE)
ARCHITECT live-tested full system. 10 bugs found + fixed: 1 CRITICAL (NEVER_LEAVE bypass). 10 atomic commits.

### T-086: TUI Aesthetic Overhaul (CERTIFIED)
V2 phosphor aesthetic, half-block logo, event-to-human translation, boot splash. 15 bugs found and fixed. 92 TUI tests.

### OIKOS-BACKLOG-001: Handler Decomposition (CERTIFIED)
Handler god-function: 862->161 lines (81% reduction). 5 pipeline modules. NEVER_LEAVE gates preserved. 26 new tests.

### T-101: Sanitized Push (COMPLETE)
9-check pre-flight audit. Git filter-repo author rewrite (614 commits -> oikos-os). Repo PUBLIC 2026-03-29.

### T-102: Approval UI (CERTIFIED)
ASK_FIRST tools functional across all interfaces. 6 API endpoints. TUI ApprovalBar. CLI routing. 33 new tests.

### T-110: Rooms v2 Integration (CERTIFIED)
System prompt builder, deferred tools + personality + vault caps. Token savings ~19-49K/call. 39 new tests.

### T-111: CENSOR Audit Fixes (CERTIFIED)
~75 findings across 4 gates. Gate 1: 30+ `str(e)` leakage sanitized. 18 new tests.

### T-079 + T-105: Daemon/Inference Decoupling (CERTIFIED)
`LocalInferenceManager` protocol + `OllamaManager`. Config mtime watcher. Restart backoff. Stop-file IPC. 22 new tests.

### T-114: Event Loop Pollution Fix (CERTIFIED)
Replaced deprecated asyncio patterns across 8 test files (50 call sites).

### T-115: Status Key Fix (CERTIFIED)
Post-merge audit: updated deleted key references.

### T-104: CLI Completion Pass (CERTIFIED)
"Bare command = read state, command + arg = write state." 13 new/modified commands. SmartGroup shorthand. 23 new tests.

### T-116: Routing Transparency (CERTIFIED)
`RoutingTrace` dataclass. Human-readable badge across all 4 interfaces. 12 fields. 17 new tests.

### T-117: Settings Exposure (CERTIFIED)
`SettingDef` registry. 21 settings across 3 tiers. Hot-reload. Type coercion. 15 new tests.

### T-118: Per-Room Generation Params (CERTIFIED)
`resolve_generation_params()` helper. Room > Global precedence. Cloud max_tokens cap. 15 new tests.

### T-119: Background Notifications (CERTIFIED)
NotificationManager with three-tier policy. 5 new emission points. Ring buffer + API. TUI/Web/Desktop escalation. 58 new tests + 4 vitest.
