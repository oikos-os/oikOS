<p align="center">
  <img src="brand/oikos_mark_canonical.svg" width="120" alt="oikOS">
</p>

<h1 align="center">oikOS</h1>
<p align="center"><strong>Your Sovereign AI Operating System</strong></p>

<p align="center">
  <img src="https://img.shields.io/badge/tests-1%2C175_passing-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/MCP_tools-41-blue" alt="MCP Tools">
  <img src="https://img.shields.io/badge/docker-3_containers-blue" alt="Docker">
  <img src="https://img.shields.io/badge/version-v1.2.0-orange" alt="Version">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
</p>

---

## What is oikOS?

oikOS is a local-first AI operating system that gives you sovereign control over your AI stack. It runs on your machine, protects your data, and connects any AI model to your personal knowledge vault through a privacy-enforced MCP server. No cloud dependency. No telemetry. Your context, your rules.

---

## Quick Start

```bash
# Docker (recommended)
docker compose up

# Manual
pip install -e .
oikos serve --dev
```

The Docker stack starts three containers:

| Container | Port | Purpose |
|---|---|---|
| oikos-core | 8420, 8421 | FastAPI + MCP server |
| ollama | 11434 | Local inference (GPU) |
| searxng | 8888 | Sovereign web search |

All ports are localhost-only by default.

---

## Why oikOS?

|  | Cloud AI | oikOS |
|---|---|---|
| **Privacy** | Your data on their servers | Your data on your machine. NEVER_LEAVE enforcement. |
| **Cost** | Per-token billing | Local inference is free. Cloud is opt-in fallback. |
| **Memory** | Conversation resets | Persistent vault with hybrid search (BM25 + vector) |
| **Agents** | Limited tool use | 41 MCP tools with privacy + autonomy middleware |
| **Security** | Trust the provider | 10-probe adversarial gauntlet. PII scrubbing. Audit log. |
| **Control** | Their rules | Your rules. Open formats. Exit guarantee. |

---

## 41 MCP Tools

Every tool goes through a 7-layer middleware chain: auth, error handling, privacy classification, autonomy control, rate limiting, cost tracking, and audit logging.

| Toolset | Tools | Description |
|---|---|---|
| **vault** (5) | search, compile, index, ingest, stats | Hybrid search, context compilation, vault health |
| **system** (12) | status, state, gauntlet, session, daemon, config, exec, notify | System management and monitoring |
| **file** (8) | read, list, search, write, edit, move, copy, delete | Scope-validated filesystem operations |
| **browser** (6) | fetch, search, extract, screenshot, navigate, monitor | Web perception (httpx + Playwright + SearXNG) |
| **research** (5) | queue, run, review, approve, reject | Autonomous research with Architect review |
| **git** (2) | status, log | Repository status for allowed paths |
| **oracle** (1) | status | Prediction agent monitoring |

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

One decorator. The framework handles everything else.

---

## Architecture

```
core/
+-- cognition/       Inference routing, multi-provider (Ollama, Anthropic, Google, OpenAI)
+-- memory/          Hybrid search (BM25 + vector), LanceDB, session management
+-- identity/        Coherence checking, contradiction detection, input guard
+-- safety/          PII detection (Presidio), output filtering, sensitivity
+-- autonomic/       FSM state machine, VRAM management, daemon, calibration
+-- interface/       CLI, FastAPI + WebSocket, configuration
+-- agency/
|   +-- browser/     Playwright + httpx + SearXNG (6 tools)
|   +-- research/    Autonomous research agent (5 tools)
|   +-- (others)     File agent, autonomy matrix, context engine, planner
+-- framework/       @oikos_tool decorator, OikosServer, 7-layer middleware, 41 tools
```

### Privacy Tiers

| Tier | Behavior |
|---|---|
| `NEVER_LEAVE` | Content never transmitted to any remote client. Vault, identity, credentials. |
| `SENSITIVE` | PII scrubbed before cloud routing. Anonymized in audit log. |
| `SAFE` | No restrictions. System status, state queries. |

### Autonomy Levels

| Level | Behavior |
|---|---|
| `SAFE` | Executes immediately. |
| `ASK_FIRST` | Returns a proposal for Architect approval. |
| `PROHIBITED` | Blocked unconditionally. |

---

## Coming Soon: oikOS Rooms

Different AI minds for different parts of your life.

Each Room is a scoped AI space within your household -- its own vault, tools, voice, and autonomy level. A Room for work. A Room for creative projects. A Room for health. A Room for finance. Each remembers its own context and speaks in its own voice.

*Phase 8: The Household. oikOS means household in Greek.*

---

## Tech Stack

- **Python 3.12+** -- primary language
- **Ollama** -- local inference (qwen2.5:14b primary, 7b fallback)
- **LanceDB** -- embedded vector database (no server)
- **FastAPI** -- API server + WebSocket
- **MCP SDK** -- Model Context Protocol (Claude Desktop + Code)
- **Playwright** -- headless browser (on-demand)
- **SearXNG** -- self-hosted search (Docker)
- **React 19 + Vite 6** -- frontend
- **Docker Compose** -- 3-container sovereign stack

---

## Development

```bash
# Run tests
python -m pytest tests/ -q

# Run gauntlet (adversarial security probes)
oikos gauntlet

# Start MCP server (stdio for Claude Desktop)
python -m core.framework --transport stdio --toolsets vault,system,file

# Start MCP server (HTTP for network clients)
python -m core.framework --transport http
```

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
  If this project resonates with you, please consider giving it a star.
</p>
