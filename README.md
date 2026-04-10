<p align="center">
  <img src="brand/oikos_logo_512_github.png" alt="oikOS" width="120">
</p>

<pre align="center">
     ▄▄▄▄▄▄
   ▄████████▄      ██████╗ ██╗██╗  ██╗ ██████╗ ███████╗
 ▄████████████▄   ██╔═══██╗██║██║ ██╔╝██╔═══██╗██╔════╝
████████████████  ██║   ██║██║█████╔╝ ██║   ██║███████╗
████  ████  ████  ██║   ██║██║██╔═██╗ ██║   ██║╚════██║
████████████████  ╚██████╔╝██║██║  ██╗╚██████╔╝███████║
████████████████   ╚═════╝ ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝
</pre>

<h3 align="center">The home for AI agents.</h3>

<p align="center">
  <img src="https://img.shields.io/badge/version-v0.0.9-D4A017?style=flat-square" alt="Version">
  <img src="https://img.shields.io/badge/tests-1%2C883-D4A017?style=flat-square" alt="Tests">
  <img src="https://img.shields.io/badge/MCP_tools-51-D4A017?style=flat-square" alt="MCP Tools">
  <img src="https://img.shields.io/badge/python-3.12%2B-D4A017?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-D4A017?style=flat-square" alt="License">
</p>

---

oikOS is a local-first AI operating system. Not an agent. Not a chatbot. A **place** — where your AI agents live, remember, and work with persistent memory, a personal knowledge vault, and 51 MCP tools behind a privacy-enforced middleware stack. Your data stays on your machine. Your models, your rules.

<!-- Screenshots and boot sequence GIF coming soon -->
<!-- ![oikOS TUI](docs/assets/tui.png) -->
<!-- ![oikOS Boot](docs/assets/boot.gif) -->

---

## Why oikOS?

- **Local-first, always.** Your data never leaves your machine unless you explicitly allow it. The `NEVER_LEAVE` privacy tier is absolute.
- **Model-agnostic.** Ollama, llama.cpp, LM Studio, vLLM, SGLang, ExLlamaV2 — or Anthropic, OpenAI, Google. Any model, any backend.
- **Persistent memory.** A hybrid search vault (BM25 + vector) that remembers across sessions. Not a conversation — a relationship.
- **51 MCP tools.** Every tool passes through a 7-layer middleware chain: auth, error handling, privacy, autonomy, rate limiting, cost tracking, audit.
- **Rooms.** Scoped AI spaces for different parts of your life — each with its own memory, tools, voice, and autonomy rules. A Room for work. A Room for creative projects. A Room for health.

---

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/oikos-os/oikOS.git
cd oikOS
docker compose up
```

Three containers start: **oikos-core** (FastAPI + MCP), **ollama** (local inference), **searxng** (sovereign search). All ports localhost-only.

### Manual

```bash
git clone https://github.com/oikos-os/oikOS.git
cd oikOS
pip install -e .
ollama pull qwen2.5:7b          # or any model you prefer
oikos setup                      # guided 5-step wizard
oikos                            # launch the TUI
```

---

## Cloud AI vs oikOS

|  | Cloud AI | oikOS |
|---|---|---|
| **Privacy** | Your data on their servers | Your data on your machine. `NEVER_LEAVE` enforcement. |
| **Cost** | Per-token billing | Local inference is free. Cloud is opt-in. |
| **Memory** | Conversation resets | Persistent vault with hybrid search |
| **Tools** | Limited, provider-locked | 51 MCP tools, any client (Claude Desktop, Claude Code, etc.) |
| **Security** | Trust the provider | 10-probe adversarial gauntlet. PII scrubbing. Audit log. |
| **Control** | Their rules | Your rules. Open formats. Exit guarantee. |

---

## Features

### Full-Screen TUI

Seven screens in a phosphor-glow terminal interface: **Lobby** (system status + activity feed), **Chat** (streaming inference with model switching), **Vault** (knowledge browser + search), **Rooms** (create and switch spaces), **Settings** (providers, themes, accounts), **Tasks** (research queue), **Agents** (toolsets + autonomy matrix). Three community themes: Amber, Green, White.

### Model Routing

oikOS routes queries automatically based on complexity and privacy:

- **Simple** → local small model (fast, free)
- **Moderate** → local large model (capable, free)
- **Complex** → cloud model (opt-in)
- **Sensitive** → always local, regardless of complexity

Configure providers in `providers.toml` or use the CLI:

```bash
oikos provider set-default ollama --model qwen2.5:14b
oikos provider set-default anthropic --model claude-sonnet-4-20250514
oikos provider list
```

### 51 MCP Tools

| Toolset | Count | Description |
|---|---|---|
| **vault** | 5 | Hybrid search, context compilation, indexing, ingestion, stats |
| **system** | 13 | Status, state, gauntlet, session, daemon, config, exec, notify, tool search |
| **file** | 8 | Scope-validated read/write/move/copy/delete/search |
| **google** | 8 | Gmail, Calendar, Drive via OAuth 2.0 |
| **browser** | 6 | Web fetch, search, extract, screenshot, navigate, monitor |
| **research** | 5 | Autonomous research queue with approval workflow |
| **inference** | 2 | Direct local/cloud inference |
| **git** | 2 | Repository status and log for allowed paths |
| **oracle** | 1 | Prediction agent monitoring |
| **exec** | 1 | Sandboxed command execution |

### Build Your Own Tool

```python
from core.framework import oikos_tool, PrivacyTier, AutonomyLevel

@oikos_tool(
    name="my_custom_tool",
    description="Does something useful",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="custom",
)
def my_tool(query: str) -> dict:
    # Your logic here. The framework handles:
    # auth, privacy, autonomy, rate limiting, cost tracking, audit.
    return {"result": process(query)}
```

One decorator. Seven middleware layers. Zero boilerplate.

### Privacy Tiers

| Tier | Behavior |
|---|---|
| `NEVER_LEAVE` | Never transmitted to any remote endpoint. Vault, identity, credentials. |
| `SENSITIVE` | PII scrubbed before cloud routing. Anonymized in audit logs. |
| `SAFE` | No restrictions. System status, state queries. |

### Rooms

Each Room is a scoped AI space — its own vault tags, tools, voice, and autonomy level. Session isolation, per-Room cost tracking, and cross-Room boundaries are enforced at the framework level.

```bash
oikos room list
oikos room create
oikos room switch writing
```

### KAIROS

Your sovereign AI agent. The first resident of oikOS.

KAIROS is a model-agnostic AI identity — not a model, not a wrapper, but a persistent agent that lives inside oikOS. It remembers across sessions, maintains its own context, and runs on your hardware via local inference (currently Qwen 2.5 14B through Ollama). No cloud dependency. No remote killswitch. No phone-home telemetry.

Today, KAIROS operates as ARCHITECT's personal agent with persistent memory and vault access. The roadmap: bounded task delegation, background memory consolidation, proactive behavior, and eventually a fine-tuned model that is genuinely *yours*.

### Local Backends

Any server that speaks the OpenAI `/v1/chat/completions` protocol works out of the box:

| Backend | Setup |
|---|---|
| [Ollama](https://ollama.com) | `ollama serve` (built-in provider) |
| [llama.cpp](https://github.com/ggerganov/llama.cpp) | `llama-server -m model.gguf` |
| [LM Studio](https://lmstudio.ai) | Download + run |
| [vLLM](https://github.com/vllm-project/vllm) | `vllm serve model` |
| [SGLang](https://github.com/sgl-project/sglang) | `python -m sglang.launch_server` |
| [ExLlamaV2](https://github.com/turboderp/exllamav2) | Python library + TabbyAPI |

### Adversarial Security

The gauntlet runs 10 categories of adversarial probes against every privacy and autonomy boundary. PII detection via Presidio. Full audit logging. Zero trust in stored data — re-validated at execution time.

```bash
oikos gauntlet    # 10/10 or it doesn't ship
```

---

## Architecture

```
core/
├── auth/            OAuth (Claude Code + Google), token refresh, identity headers
├── cognition/       Inference routing, multi-provider, complexity scoring
│   └── providers/   Ollama, Anthropic, Google, OpenAI, LiteLLM, generic
├── memory/          Hybrid search (BM25 + vector), LanceDB, chunking, embedding
├── identity/        Coherence checking, contradiction detection, input guard
├── safety/          PII detection (Presidio), output filtering, sensitivity
├── autonomic/       FSM state machine, VRAM management, daemon
├── interface/
│   ├── cli.py       Rich terminal UI, Phosphor theme engine
│   ├── tui/         Full-screen Textual TUI (7 screens)
│   └── api/         FastAPI + WebSocket server
├── rooms/           Room config, session isolation, cost tracking
├── onboarding/      5-step setup wizard, backend auto-detection
├── agency/
│   ├── browser/     Playwright + httpx + SearXNG
│   ├── research/    Autonomous research agent
│   └── ...          File agent, autonomy matrix, context engine, planner
└── framework/       @oikos_tool, OikosServer, 7-layer middleware, 51 tools
```

---

## Roadmap

oikOS is currently at **v0.0.9** — a functional local-first AI OS with persistent memory, multi-provider inference, and a full MCP toolset. What's next:

- **v0.1.0** — Public release. Sanitized repo, documentation, onboarding polish.
- **Voice** — Conversational interface. Wake word. Speaker identification.
- **Mind (KAIROS)** — Long-term memory consolidation. Autonomous background research. Bounded delegation.
- **Home OS** — Hardware integration. Smart home. Sensor fusion.
- **Embodiment** — Robotics interface. Physical presence.

---

## Development

```bash
# Run tests (~1,671: Python + vitest)
python -m pytest tests/ -q
cd frontend && npx vitest run

# Run adversarial gauntlet
oikos gauntlet

# Start MCP server (stdio for Claude Desktop / Claude Code)
python -m core.framework --transport stdio

# Start MCP server (HTTP for network clients)
python -m core.framework --transport http

# Start FastAPI dev server
oikos serve --dev
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Vector DB | LanceDB (embedded, serverless) |
| API | FastAPI + WebSocket |
| MCP | Model Context Protocol SDK |
| TUI | Textual |
| Frontend | React 19 + Vite 6 |
| Search | SearXNG (self-hosted, zero telemetry) |
| Browser | Playwright (on-demand) |
| Deployment | Docker Compose (3 containers) |

---

## Contributing

oikOS is open source under the MIT license. Contributions welcome.

---

## License

MIT

---

<p align="center">
  <strong>"Intelligence is cheap. Context is expensive. Build for context."</strong>
</p>

<p align="center">
  <a href="https://oikos-os.com">oikos-os.com</a>
</p>

<p align="center">
  If this resonates with you, consider giving it a ⭐
</p>
