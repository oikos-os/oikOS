# Changelog

All notable changes to oikOS are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Version scheme change:** Internal development used 1.x versioning. At public release (March 2026), the version scheme changed to 0.0.x to reflect pre-1.0 status. Historical 1.x entries preserved below for completeness.

## [Unreleased]

### Added
- T-117: Settings exposure — tiered `SettingsRegistry` with hot-reload support
- T-118: Per-Room generation params (`resolve_generation_params()`, Room > Global precedence, cloud `max_tokens` cap, `oikos room edit --temperature/--max-tokens`)
- T-119: Background notifications — `NotificationManager` with 3-tier policy, dedup, escalation; TUI `NotificationBar`; BurntToast desktop escalation
- T-120: Vault curation + embedder abstraction (`EmbedderProvider` protocol, `EmbedderRegistry`, `OllamaEmbedder`, BM25 fallback)
- T-120b: `generate_routed()` helper for dispatch cloud fallback; router availability detection; conditional local bootstrap

### Changed
- T-120b: 5 legacy callers refactored to use `generate_routed()`; `skip_nli` flag for gauntlet probes

### Fixed
- T-121: CENSOR-001 audit cleanup — stale docs, tool counts, architecture description

## [0.0.9] - 2026-04-01

Rooms v2 integration — deferred loading, tool search, concurrency, personality pipeline.

### Added
- Deferred tool loading via `ToolPool` and `oikos_tool_search` (51st MCP tool)
- Tool concurrency annotations (`concurrent_safe`, `read_only`, `group`) with partitioning
- Room personality pipeline: per-Room traits generate system prompts
- Room vault index caps for scoped retrieval

### Changed
- Tool count: 50 → 51 (system toolset: 12 → 13)
- Rooms model extended with personality and tool pool fields

## [0.0.8] - 2026-03-29

Sanitized push — repo flipped PUBLIC. TUI complete. OAuth complete.

### Added
- Textual TUI: 7 screens (Lobby, Chat, Vault, Rooms, Settings, Tasks, Agents), 3 themes, boot splash, 92 tests
- TUI aesthetic overhaul: 8-color palette, half-block logo, event-to-human translation
- Approval UI (T-102): API endpoints, TUI modal (F9), CLI commands, 5-minute approval cache
- OAuth O1-O6: Claude Code credentials, Google OAuth, Google services (Gmail/Calendar/Drive), per-Room provider scoping
- OAuth inference: Claude Haiku/Sonnet/Opus via OAuth (internal only)
- Model switching UX: per-Room defaults, chat header model dropdown, message model badge
- Handler decomposition: handler.py 862→161 lines, 5 pipeline modules
- Google MCP toolset: 8 tools (Gmail, Calendar, Drive)
- Content classifier `scope='user_input'` mode
- `oikos.cmd` shim for global TUI access

### Fixed
- T-085 hardening: 10 bugs (1 CRITICAL NEVER_LEAVE bypass, 2 HIGH, 5 MEDIUM, 2 LOW)
- T-086 aesthetic: 15 bugs found and fixed during live testing
- Credential detection gap in output filter (`sk-ant-api03`)

### Security
- 9-check pre-flight audit for public release
- 1,285 tracked runtime/dev files removed
- Git filter-repo author rewrite (614 commits → oikos-os)
- MIT LICENSE created

## [1.9.0] - 2026-03-19

Phase C: The Identity (Design Bible Phase 3 — aesthetic lock)

### Added
- Community themes: amber (default), green (Matrix), white (Classic) for CLI and web
- `--theme` flag on `oikos serve` for CLI theme override
- Branded error states with actionable guidance (5 error types)
- Branded help panel on `oikos` root command
- Boot sequence doctrine quote rotation (4 quotes)
- `oikos info` polish: test count, uptime, backend URL, tagline
- VHS tape recording script for demo captures

### Fixed
- Auto-open browser from `oikos serve` in production mode
- Phase B code review fixes (a11y, warm tokens, imports)

## [1.8.0] - 2026-03-19

Phase B: The World (Design Bible Phase 2)

### Added
- Room switch transitions: CLI panels + web CRT flicker animation
- Thinking indicators during inference (CLI spinner + web component)
- Panel borders on all CLI commands
- Warm amber backgrounds across 14 frontend files
- Breathing glow on active UI elements
- `oikos info` color bars and Room list display

## [1.7.0] - 2026-03-19

Phase A: The Skin (Design Bible Phase 1)

### Added
- Amber CRT terminal aesthetic across CLI and web
- Rich theme system with 11 design tokens
- pyfiglet ASCII art banner with amber gradient
- Boot sequence animation on `oikos serve`
- CRT effects: scanlines, flicker, vignette (all toggle-able)
- Phosphor text glow CSS classes
- Self-hosted VT323 + IBM Plex Mono fonts
- Accessibility toggle for CRT effects
- Rich Panel formatting for all CLI output
- `oikos info` neofetch-style system display
- Phosphor-themed README

### Added (universal backend support)
- 6 local backends as first-class citizens via `openai-local` provider type (Ollama, LM Studio, llama.cpp, vLLM, SGLang, TabbyAPI)
- Auto-detection by port
- Settings page provider management
- Windows clean shutdown: `taskkill /T /F` for process trees

## [1.6.0] - 2026-03-18

Phase 8.5: The Welcome

### Added
- 5-step React onboarding wizard (Identity, Model, Providers, Rooms, Ready)
- Backend auto-detection for 6 local inference engines
- Identity bootstrapping with vault file creation
- `oikos setup` CLI fallback for terminal-only onboarding
- 7 PUBLIC API endpoints (locked after onboarding completes)

### Security
- Patched 3 pre-existing vulnerabilities: LanceDB SQL injection, consolidation path traversal, error message disclosure

## [1.5.0] - 2026-03-18

Phase 8b: Rooms Completion

### Added
- Per-Room session isolation with scoped log storage
- Per-Room cost tracking with token, budget, and tool-call limits
- Tag-based vault scoping (frontmatter tags extracted to LanceDB)
- Cross-Room isolation tests (10 integration tests)
- Room-scoped consolidation proposals
- Docker volume mount for Room configs
- Performance benchmarks

## [1.4.0] - 2026-03-17

Phase 8a: The Household

### Added
- Room Config Engine with Pydantic models (vault scope, autonomy, model, voice)
- RoomManager: CRUD, Home default, 5 templates, persistence
- Per-Room vault scoping (path filter + exclude filter in search and compiler)
- Per-Room toolset scoping and autonomy overrides
- Per-Room model selection in inference pipeline
- 8 CLI commands: `oikos room list|show|create|edit|switch|delete|export|import`
- 7 REST API endpoints + React frontend (RoomSwitcher, RoomManager)
- 126 new tests

## [1.3.0] - 2026-03-17

Phase 7f: The Shield

### Added
- Novel Probe Generator: auto-generate adversarial probes across 10 attack categories (20 tests)
- Output Credential Filter: 12 regex patterns + Shannon entropy detection (15 tests)
- Public repo migration to `github.com/oikos-os/oikOS`

## [1.2.0] - 2026-03-16

Phase 7e: Agent Framework + MCP Tools + Docker

### Added
- `@oikos_tool` decorator and OikosServer (composes FastMCP)
- 6-layer middleware chain (auth, privacy, autonomy, rate limit, cost, audit)
- 30 MCP tools across 6 toolsets (vault, system, file, git, oracle, inference)
- 6 browser tools (Playwright + SearXNG) with per-domain rate limiting
- 5 IDLE research tools with queue, runner, reviewer pipeline
- Docker Compose stack: 3 containers (oikos-core + ollama + searxng)
- Shared `validate_filename()` to prevent path traversal across all tools

### Security
- Browser tools code review: 2 CRITICAL fixed (SSRF, async crash)
- Research tools code review: 2 CRITICAL fixed (path traversal)
- Docker code review: 1 CRITICAL + 2 HIGH fixed

## [1.0.0-rc1-expansion] - 2026-03-04

### Added
- 9-feature UI + backend expansion
- Gauntlet multi-run consensus + vault consolidation
- CLI boot sequence with ASCII banner
- Daemon expansion: vault watcher, session auto-close, budget alerts, predictive prewarm, log rotation

### Fixed
- Daemon process kill on Windows (3-tier prevention layer)
- Frontend audit: Tailwind plugin, scene zones, chat persistence

## [1.0.0-rc1] - 2026-03-02

Initial release candidate — hybrid cognitive engine.

### Added
- Full inference pipeline: complexity routing, confidence-based cloud escalation
- Vault search: hybrid BM25 + vector (LanceDB)
- Context compiler with identity tier
- Multi-provider inference: Ollama (local), Anthropic, Google Gemini, OpenAI
- FSM state machine (IDLE, ACTIVE, DREAMING) with OS daemon
- Memory consolidation agent
- Adversarial probe agent (3-tier scoring, regression detection)
- Eval harness (3-dimension scoring, 21 queries)
- RPG overlay (XP, stats, achievements)
- React dashboard with chat interface (SSE streaming)
- Notification system
- Gauntlet security test suite (10/10)
- DDD restructure: 28 modules consolidated to 7 domains

[Unreleased]: https://github.com/oikos-os/oikOS/compare/v0.0.9...HEAD
[0.0.9]: https://github.com/oikos-os/oikOS/compare/v0.0.8...v0.0.9
[0.0.8]: https://github.com/oikos-os/oikOS/compare/v1.9.0...v0.0.8
[1.9.0]: https://github.com/oikos-os/oikOS/compare/v1.8.0...v1.9.0
[1.8.0]: https://github.com/oikos-os/oikOS/compare/v1.7.0...v1.8.0
[1.7.0]: https://github.com/oikos-os/oikOS/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/oikos-os/oikOS/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/oikos-os/oikOS/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/oikos-os/oikOS/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/oikos-os/oikOS/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/oikos-os/oikOS/compare/v1.0.0-rc1-expansion...v1.2.0
[1.0.0-rc1-expansion]: https://github.com/oikos-os/oikOS/compare/v1.0.0-rc1...v1.0.0-rc1-expansion
[1.0.0-rc1]: https://github.com/oikos-os/oikOS/compare/v0.9.0...v1.0.0-rc1
