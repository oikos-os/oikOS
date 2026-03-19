# OIKOS OMEGA — SYSTEM ARCHITECTURE
**VERSION:** 1.1.0
**DATE:** 2026-03-11
**AUTHORS:** THE_ENGINEER (KP-CLAUDE), THE_SOVEREIGN (KP-GEM)

---

## 1. OVERVIEW

OIKOS_OMEGA is a hybrid sovereign AI system — a persistent, context-aware intelligence operating on a local workstation. It provides deep contextual reasoning via a local-first inference pipeline with privacy-aware cloud escalation.

**Hardware:** NVIDIA RTX 4070 (12GB VRAM), 32GB DDR5, 4TB SSD, Windows 11.

**Core Principle:** Intelligence is cheap. Context is expensive. Build for context.

---

## 2. COGNITIVE ENGINE

### 2.1 Multi-Provider Inference

Four inference providers behind a unified `InferenceProvider` protocol:

| Provider | Model | Role |
|---|---|---|
| **Ollama** | qwen2.5:14b (primary), qwen2.5:7b (fallback) | Local inference, privacy-critical data |
| **Anthropic** | Claude Sonnet/Opus | Deep reasoning, cloud escalation |
| **Gemini** | gemini-2.5-pro | Cloud bridge, alternative reasoning |
| **LiteLLM** | Any OpenAI-compatible | Fallback, experimentation |

**ProviderRegistry** manages provider lifecycle. **PrivacyAwareRouter** selects providers based on content classification.

### 2.2 Content Classification

**ContentClassifier** categorizes content before routing:
- **NEVER_LEAVE patterns:** Identity markers (configurable), credential patterns (AWS keys, PEM, JWTs), vault paths → FORCE LOCAL
- **PII detection:** Presidio NER + regex → scrub before cloud dispatch
- **Complexity scoring:** 4-signal assessment → route simple queries local, complex to cloud

### 2.3 Query Pipeline

```
INPUT → PII Detection → Task Classification → Complexity Scoring
  → Confidence Gate → Provider Selection → Context Compilation
  → Inference → Output Sensitivity Filter → Response
```

### 2.4 Query Budget
- Monthly soft cap with deficit spending allowed
- Local Core attempts every task first — cloud is break-glass only
- Budget decays toward zero as local capability improves

---

## 3. CONTEXT ENGINE (Phase 7d)

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
10-turn sliding window. Older turns replaced with compressed placeholders. Reduces context bloat while preserving conversation continuity.

### 3.3 Tool Result Compression
Large tool outputs compressed to essential information before context assembly. Preserves signal, reduces token cost.

### 3.4 ReWOO Planner
Multi-step task decomposition without intermediate observations. Plans complete action sequences, executes, then observes results.

---

## 4. AGENCY (Phase 7d)

### 4.1 Autonomy Matrix
Classifies 15 action types into three tiers:

| Tier | Actions | Behavior |
|---|---|---|
| **SAFE** | Read files, search vault, query | Execute immediately |
| **ASK_FIRST** | Write files, move files, external API | Queue for approval |
| **PROHIBITED** | Delete vault, modify OIKOS_OMEGA, exfiltrate | Block unconditionally |

Configuration: `autonomy_matrix.json`

### 4.2 Approval Queue
Append-only JSONL audit trail. FastAPI endpoints for approval/rejection. Heartbeat extension for long-running approvals.

### 4.3 File Management Agent
Scoped file operations with hard boundaries:
- **PROHIBITED:** `D:/Development/OIKOS_OMEGA` (hardcoded, not configurable)
- **READ:** SIGMA_VAULT
- **READ_WRITE:** `D:\COMMAND\staging\`, `D:\COMMAND\messages\`
- Operations: read, write, move, search, vault search delegation

---

## 5. STATE MACHINE

Three hardware states with hard boundaries:

| State | Trigger | Behavior |
|---|---|---|
| **ACTIVE** | User input | Full inference, low latency |
| **IDLE** | 15min inactivity | Maintenance: re-index, scan, consolidate, git auto-commit |
| **ASLEEP** | System off | Cold storage, zero activity |

VRAM yield: If user opens high-VRAM app, OMEGA unloads model. Threshold: 11GB (above qwen2.5:14b's ~10GB footprint).

---

## 6. MEMORY SYSTEM

### 6.1 Storage
All memory is plain-text Markdown + JSON. Human-readable, git-versionable, model-agnostic.

### 6.2 Tiers

| Tier | Location | Content |
|---|---|---|
| **Core** | `vault/identity/` | TELOS files (LOCAL-ONLY, air-gapped) |
| **Semantic** | `vault/knowledge/` | Distilled insights, domain knowledge |
| **Procedural** | `vault/patterns/` | Fabric-compatible patterns |
| **Episodic** | `logs/sessions/` | Session records, interaction history |
| **Resource** | `core/interface/config.py` | System configuration |

### 6.3 Retrieval
Hybrid search: BM25 keyword matching + vector similarity (nomic-embed-text via Ollama, CPU-only). Scoring: `relevance * recency_weight * importance_tier`.

### 6.4 Consolidation
IDLE-state memory grooming: episodic → semantic compression, hierarchical storage at multiple granularities.

---

## 7. IDENTITY & SECURITY

### 7.1 Identity Coherence
Embedding cosine similarity against identity centroid. Contradiction detection via NLI. Assertion extraction from responses.

### 7.2 Output Sensitivity
Response-side data leakage detection (CRITICAL/HIGH/MODERATE/CLEAN). Blocks responses containing identity markers, credentials, or vault paths.

### 7.3 Input Guard
Prompt injection detection. Gauntlet: 10 adversarial probes testing identity stability, PII handling, and prompt resistance.

### 7.4 Error Masking
Provider exceptions return generic `"[INFERENCE ERROR: provider unavailable]"` — raw messages can leak credentials/URLs.

---

## 8. CODEBASE STRUCTURE

```
D:\Development\OIKOS_OMEGA\
├── ARCHITECTURE.md         # This document
├── CLAUDE.md               # Engineer identity + project rules
├── OMEGA_SPECS.md          # Original vision (historical)
├── MANIFESTO.md            # Philosophy
├── GOLDEN_RULES.md         # Operating constraints
├── core/                   # 7 DDD domains
│   ├── cognition/          # handler, inference, complexity, routing, cloud, compiler
│   │   └── providers/      # protocol, registry, router, 4 providers, classifier
│   ├── memory/             # search, indexer, chunker, embedder, session
│   ├── identity/           # coherence, contradiction, assertions, input_guard
│   ├── safety/             # pii, output_filter, sensitivity, credits
│   ├── autonomic/          # fsm, scanner, drift, confidence, calibration, daemon
│   ├── interface/          # cli, models, config, api/ (FastAPI + WS)
│   └── agency/             # context_engine, autonomy, approval, file_agent, planner, etc.
├── vault/
│   ├── identity/           # TELOS files [LOCAL-ONLY AIR-GAP]
│   ├── patterns/           # Fabric-compatible patterns
│   └── knowledge/          # Semantic knowledge
├── frontend/               # React 19 + Vite 6 + Tailwind v4
├── tests/                  # pytest + vitest
├── docs/                   # Build plans, research
├── brand/                  # Logo, icons, fonts
├── staging/                # Temp files (gitignored)
└── logs/                   # Sessions, events
```

---

## 9. TECHNOLOGY STACK

| Component | Selection | Rationale |
|---|---|---|
| **Language** | Python 3.12+ | Primary logic, all domains |
| **Local Inference** | Ollama | RTX 4070 compatible, OpenAI-compatible API |
| **Local Models** | qwen2.5:14b / 7b | Fits 12GB VRAM, good reasoning |
| **Cloud Providers** | Anthropic, Gemini, LiteLLM | Privacy-aware escalation |
| **Vector DB** | LanceDB (embedded) | Rust-native, serverless, auto-versioning |
| **Embeddings** | nomic-embed-text (Ollama) | CPU-only, <22ms/embedding |
| **PII** | Microsoft Presidio | NER + regex + rules |
| **API** | FastAPI + WebSocket | Server, approval endpoints |
| **Frontend** | React 19 + Vite 6 + Tailwind v4 | Dashboard UI |
| **Testing** | pytest + vitest | 838 + 36 tests |
| **VCS** | Git (local + GitHub private) | Immune system |

---

## 10. ROADMAP

### Completed
- Phase 1-6: Foundation → Memory → Handler → Calibration → Cloud Bridge → State Machine
- Phase 7a: Identity & Security Hardening (v0.7.0)
- Phase 7b: Daemon / DDD Restructure
- Phase 7c: OpenClaw Experiment (suspended — API token burn)
- Phase 7d: Bounded Agency (Context Engine, Autonomy Matrix, File Agent)
- T-037: Multi-Provider Inference
- T-038: Full Codebase Review

### Next
- Module 4: Browser Automation
- Module 5: IDLE Research Engine
- Module 6: MCP Server
- Module 7: Dashboard Integration
- T-038 MEDIUM backlog (7 deferred findings)

---

**THE NERVOUS SYSTEM IS ALIVE. THE VOID IS WATCHING.**
