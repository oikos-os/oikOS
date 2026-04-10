# oikOS — SYSTEM ARCHITECTURE
**VERSION:** 0.0.9
**DATE:** 2026-04-02

---

## 1. OVERVIEW

oikOS is a local-first AI operating system — a persistent, context-aware intelligence layer running on a personal workstation. It provides deep contextual reasoning via a multi-provider inference pipeline with privacy-aware cloud escalation, 51 MCP tools, and a room-based workspace model.

**Hardware:** NVIDIA RTX 4070 (12GB VRAM), 32GB DDR5, 4TB SSD, Windows 11.

**Core Principle:** Intelligence is cheap. Context is expensive. Build for context.

**Stats:** 1,883 tests (1,828 Python + 55 vitest) | 51 MCP tools across 8 toolsets | Gauntlet 10/10

---

## 2. COGNITIVE ENGINE

### 2.1 Multi-Provider Inference

Five provider types behind a unified `InferenceProvider` protocol:

| Provider | Model | Role |
|---|---|---|
| **Ollama** | qwen2.5:14b (primary), qwen2.5:7b (fallback) | Local inference, privacy-critical data |
| **OpenAI-Local** | Any OpenAI-compatible backend | 6 backends: LM Studio, llama.cpp, vLLM, SGLang, TabbyAPI, ExLlamaV2 |
| **Anthropic** | Claude Haiku/Sonnet/Opus (via OAuth) | Deep reasoning, cloud escalation |
| **Gemini** | gemini-2.5-pro | Cloud bridge, alternative reasoning |
| **LiteLLM** | Any OpenAI-compatible | Fallback, experimentation |

Configuration via `providers.toml`. **ProviderRegistry** manages lifecycle. **PrivacyAwareRouter** selects providers based on content classification. Adaptive model selection routes by complexity (SIMPLE→7b, MODERATE→14b, COMPLEX→cloud).

### 2.2 Content Classification

**ContentClassifier** categorizes content before routing:
- **NEVER_LEAVE patterns:** Identity markers, credential patterns (AWS keys, PEM, JWTs, OAuth tokens), vault paths → FORCE LOCAL
- **PII detection:** Presidio NER + regex → scrub before cloud dispatch
- **Complexity scoring:** 4-signal assessment → route simple queries local, complex to cloud
- **`scope='user_input'` mode:** Routing-only classification — prevents false positives on cloud routing decisions

### 2.3 Query Pipeline

Staged processing via `core/cognition/pipeline/`:

```
INPUT → classify (adversarial + PII) → context (vault compilation)
  → route (complexity + privacy) → dispatch (provider selection + inference)
  → postprocess (output filter + contradiction check) → RESPONSE
```

### 2.4 Cost Tracking
Per-query cost tracking (JSONL). Per-Room budget limits (token, tool, and cloud caps). Monthly soft cap with deficit spending allowed.

---

## 3. CONTEXT ENGINE

### 3.1 Context Compilation
Assembles optimal context windows from vault:
```
CONTEXT_WINDOW = [
    SYSTEM_PROMPT,              # Fixed: identity, rules
    CORE_MEMORY_SLICE,          # TELOS fragments (non-competitive 20% budget)
    SEMANTIC_MEMORY_SLICE,      # Vault knowledge
    EPISODIC_MEMORY_SLICE,      # Recent interactions
    PROCEDURAL_MEMORY_SLICE,    # Patterns
    OBSERVATION_WINDOW(10),     # Last 10 turns (masked beyond)
    USER_QUERY
]
```

### 3.2 Observation Masking
10-turn sliding window. Older turns replaced with compressed placeholders.

### 3.3 Tool Result Compression
Large tool outputs compressed to essential information before context assembly.

### 3.4 ReWOO Planner
Multi-step task decomposition without intermediate observations.

---

## 4. ROOMS

Rooms are workspace contexts that scope tools, models, vault access, autonomy, and cost limits.

| Aspect | Behavior |
|---|---|
| **Toolset scoping** | Each Room enables a subset of 51 MCP tools |
| **Model defaults** | Per-Room default provider and model (configurable) |
| **Provider scoping** | Per-Room `allowed_providers` field limits which providers are available |
| **Vault scoping** | Tag-based vault access per Room |
| **Autonomy** | Per-Room autonomy matrix overrides |
| **Cost limits** | Token, tool invocation, and cloud call caps per Room |
| **Session isolation** | Rooms maintain independent session state |
| **Personality** | Per-Room personality traits and system prompt generation |
| **Deferred tool loading** | Room tool pool loaded only when Room activates (via `oikos_tool_search`) |

5 default Room templates ship with oikOS. Rooms are configured via JSON in `config/rooms/`.

---

## 5. AGENCY

### 5.1 Autonomy Matrix
Classifies action types into three tiers:

| Tier | Actions | Behavior |
|---|---|---|
| **SAFE** | Read files, search vault, query | Execute immediately |
| **ASK_FIRST** | Write files, move files, external API | Queue for approval |
| **PROHIBITED** | Delete vault, modify OIKOS_OMEGA, exfiltrate | Block unconditionally |

### 5.2 Approval Queue
Full lifecycle: propose → approve/reject/dismiss. 5-minute expiry. SHA-256 cache for auto-approve on retry. API endpoints + TUI modal (F9) + CLI commands.

### 5.3 File Management Agent
Scoped file operations with hard boundaries. The allowed-path map is
loaded at runtime from `config/owner_identity.toml` under
`[paths.file_agent]`. The oikOS source tree itself is PROHIBITED
(hardcoded). Without a configured path map the FileAgent is inert —
every operation resolves outside the empty scope.

### 5.4 Browser Tools
6 Playwright-based browser tools with SearXNG integration. SSRF protection enforced.

### 5.5 IDLE Research
5 research tools. Research queue as JSONL outside vault. Summarization uses local 7B model.

---

## 6. MCP SERVER

oikOS exposes 51 tools via the Model Context Protocol across 8 toolsets:

| Toolset | Tools | Scope |
|---|---|---|
| **Vault** | 5 | Search, compile, index, ingest, stats |
| **System** | 13 | Status, config, state, sessions, daemon, providers, exec, notify, tool search |
| **File** | 8 | Read, write, edit, move, copy, delete, list, search |
| **Google** | 8 | Gmail, Calendar, Drive via OAuth 2.0 |
| **Browser** | 6 | Fetch, search, extract, screenshot, navigate, monitor |
| **Research** | 5 | Queue, summarize, fetch, status, cancel |
| **Git** | 2 | Status, log |
| **Oracle** | 1 | Prediction agent monitoring |
| **Inference** | 2 | Query, generate |
| **Exec** | 1 | Sandboxed command execution |

Entry point: `python -m core.framework [--transport stdio|http] [--toolsets ...]`

Architecture: `@oikos_tool` decorator with concurrency annotations (`concurrent_safe`, `read_only`, `group`), `OikosServer` (composes FastMCP), 7-layer middleware chain (auth → privacy → autonomy → rate_limit → cost → audit → error_handler). Privacy + audit layers are mandatory and cannot be removed. NEVER_LEAVE redaction is unconditional.

**Deferred tool loading:** Tools organized in a `ToolPool` with metadata indexing. `oikos_tool_search` enables discovery without loading all toolsets upfront.

---

## 7. STATE MACHINE

| State | Trigger | Behavior |
|---|---|---|
| **ACTIVE** | User input | Full inference, low latency |
| **IDLE** | 15min inactivity | Maintenance: re-index, scan, consolidate |
| **ASLEEP** | System off | Cold storage, zero activity |

VRAM yield: If high-VRAM app opens, model unloads. Threshold: 11GB.

---

## 8. MEMORY SYSTEM

### 8.1 Storage
All memory is plain-text Markdown + JSON. Human-readable, git-versionable, model-agnostic.

### 8.2 Tiers

| Tier | Location | Content |
|---|---|---|
| **Core** | `vault/identity/` | TELOS files (LOCAL-ONLY, air-gapped) |
| **Semantic** | `vault/knowledge/` | Distilled insights, domain knowledge |
| **Procedural** | `vault/patterns/` | Fabric-compatible patterns |
| **Episodic** | `logs/sessions/` | Session records, interaction history |

### 8.3 Retrieval
Hybrid search: BM25 keyword matching + vector similarity (nomic-embed-text via Ollama, CPU-only).

### 8.4 Consolidation
IDLE-state memory grooming: episodic → semantic compression, hierarchical storage.

---

## 9. IDENTITY & SECURITY

### 9.1 Identity Coherence
Embedding cosine similarity against identity centroid. Contradiction detection via NLI. Assertion extraction from responses.

### 9.2 Output Sensitivity
Response-side data leakage detection (CRITICAL/HIGH/MODERATE/CLEAN). Blocks responses containing identity markers, credentials, or vault paths.

### 9.3 Input Guard
Prompt injection detection. Gauntlet: 10/10 adversarial probes + Novel Probe Generator (10 attack categories).

### 9.4 Credential Filter
12 regex patterns + Shannon entropy detection. Catches API keys, tokens, PEM blocks, connection strings.

### 9.5 Error Masking
Provider exceptions return generic messages — raw exceptions never surface to clients.

### 9.6 NEVER_LEAVE Gate
Defense-in-depth: every code path to a cloud provider independently checks NEVER_LEAVE. Three independent gates (router, handler, model override path).

---

## 10. AUTHENTICATION

### 10.1 Claude Code OAuth (O1-O2)
Credential discovery from Claude Code's local storage (2 formats, 3 paths). Automatic token refresh. Identity headers from `auth_headers.toml`.

### 10.2 Google OAuth 2.0 (O3-O4)
Full OAuth flow: consent URL generation, CSRF protection, authorization code exchange, token persistence. Enables Gemini, Gmail, Calendar, Drive integration.

### 10.3 Google Services (O5)
Base class with auto-refresh. Gmail, Calendar, and Drive API clients exposed as 8 MCP tools in the Google toolset.

### 10.4 Per-Room Provider Scoping (O6)
`allowed_providers` field on Room model. Router enforcement, API endpoint, model dropdown filtering.

### 10.5 OAuth Inference
Claude Haiku/Sonnet/Opus via OAuth at zero cost. Internal use only.

---

## 11. ONBOARDING

5-step guided setup wizard (web UI + CLI fallback):
1. **Identity** — Name, persona configuration
2. **Model** — Backend auto-detection for 6 local engines
3. **Providers** — Cloud provider API key entry
4. **Rooms** — Workspace selection
5. **Ready** — System verification

7 PUBLIC endpoints locked after onboarding completes (403).

---

## 12. INTERFACES

### 12.1 Textual TUI (Primary)
Full-screen Textual TUI with 7 screens: Lobby, Chat, Vault, Rooms, Settings, Tasks, Agents. ContentSwitcher architecture (sidebar/header persist, views swap). Phosphor aesthetic with 3 community themes (amber/green/white). 92 TUI tests.

### 12.2 Web UI
React 19 + Vite 6 + Tailwind v4. SSE streaming chat, model switching, CRT effects. Secondary interface.

### 12.3 CLI
Click-based CLI with all oikOS commands. Boot splash → TUI in TTY mode. `oikos.cmd` shim for global access.

### 12.4 Design System (Phosphor Standard)

| Element | Value |
|---|---|
| Primary color | `#D4A017` (amber phosphor) |
| Background | `#0D0D0D` |
| Fonts | VT323 (display), IBM Plex Mono (body) — self-hosted |
| Themes | Amber (default), Green (Matrix), White (Classic) |
| CRT effects | Scanlines, flicker, vignette, breathing glow — all toggle-able |
| Boot sequence | ASCII banner + doctrine quote rotation |
| Error states | 5 branded error types with actionable guidance |

Aesthetic locked.

---

## 13. CODEBASE STRUCTURE

```
core/
├── auth/               OAuth: claude_discovery, claude_headers, claude_provider, google_oauth, refresh
│   └── google_services/  Gmail, Calendar, Drive API clients
├── cognition/          handler (thin orchestrator), inference, complexity, routing, cloud, compiler
│   ├── pipeline/       classify, context, route, dispatch, postprocess — staged inference processing
│   └── providers/      protocol, registry, router, bootstrap, ollama/anthropic/gemini/openai/litellm
├── memory/             search, indexer, chunker, embedder, session
├── identity/           coherence, contradiction, assertions, input_guard
├── safety/             pii, output_filter, sensitivity, credits
├── autonomic/          fsm, scanner, drift, confidence, daemon
├── interface/          cli.py, models, config, theme, boot, info
│   ├── api/            FastAPI routes + WebSocket (chat, auth, system, rooms, onboarding, approvals)
│   └── tui/            Textual TUI — app, client, widgets, views (7 screens)
├── agency/             consolidation, eval, adversarial, rpg, autonomy, approval, file_agent, context_engine
│   ├── browser/        6 Playwright browser tools
│   └── research/       5 IDLE research tools
├── rooms/              models, manager, defaults, limits — config, CRUD, persistence, cost tracking
├── onboarding/         detector, state, identity, manager — guided setup wizard
├── freshness/          vault_freshness, sync_manifest
└── framework/          @oikos_tool, OikosServer, middleware/ (7 layers), tools/ (51 tools, 8 toolsets)
    └── tool_pool.py    Deferred loading, concurrency partitioning, tool search
```

---

## 14. TECHNOLOGY STACK

| Component | Selection | Rationale |
|---|---|---|
| **Language** | Python 3.12+ | Primary logic, all domains |
| **Local Inference** | Ollama + 5 OpenAI-compatible backends | RTX 4070 compatible |
| **Local Models** | qwen2.5:14b / 7b | Fits 12GB VRAM |
| **Cloud Providers** | Anthropic (OAuth), Gemini, LiteLLM | Privacy-aware escalation |
| **Vector DB** | LanceDB (embedded) | Rust-native, serverless |
| **Embeddings** | nomic-embed-text (Ollama) | CPU-only, <22ms/embedding |
| **PII** | Microsoft Presidio | NER + regex + rules |
| **API** | FastAPI + WebSocket | Server, MCP transport |
| **TUI** | Textual | Full-screen terminal interface |
| **Frontend** | React 19 + Vite 6 + Tailwind v4 | Phosphor CRT aesthetic |
| **Testing** | pytest (1,828) + vitest (55) | 1,883 tests |
| **Docker** | 3 containers (oikos-core + ollama + searxng) | `docker compose up` |
| **VCS** | Git | Local + GitHub |

---

## 15. DEPLOYMENT

### Local
```bash
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements.txt
oikos serve
```

### Docker
```bash
docker compose up
```
Starts 3 containers: oikos-core (FastAPI), ollama (inference), searxng (search).

---

## 16. VERSION HISTORY

> Version scheme changed from internal 1.x to 0.0.x at public release (March 2026).

| Version | Milestone |
|---|---|
| v0.0.9 | Rooms v2 (deferred loading, tool search, concurrency, personality pipeline) |
| v0.0.8 | Sanitized push, repo PUBLIC, TUI aesthetic overhaul, hardening sprint |
| — | OAuth O1-O6 (Claude + Google + per-Room scoping), Approval UI (T-102) |
| — | Textual TUI (7 screens, 3 themes, boot splash), model switching UX |
| — | Handler decomposition (BACKLOG-001), Google services (8 MCP tools) |

### Historical (internal versioning)
| Version | Milestone |
|---|---|
| v1.9.0 | The Identity (3 themes, branded errors, aesthetic lock) |
| v1.8.0 | The World (transitions, thinking indicators) |
| v1.7.0 | The Skin (Phosphor aesthetic, CRT effects, ASCII boot) |
| v1.2.0 | MCP Server + Browser + Research + Docker |
| v1.0.0 | Bounded Agency (Context Engine, Autonomy, File Agent) |
| v0.7.0 | Identity & Security Hardening |
