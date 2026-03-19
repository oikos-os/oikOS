<p align="center">

```
         _ __   ____  _____
  ____  (_) /__/ __ \/ ___/
 / __ \/ / //_/ / / /\__ \
/ /_/ / / ,< / /_/ /___/ /
\____/_/_/|_|\____//____/
```

</p>

<h3 align="center">The home for AI agents. Local-first. Privacy-sovereign. Open-source.</h3>

<p align="center">
  <img src="https://img.shields.io/badge/tests-1%2C452-D4A017?style=flat-square" alt="Tests">
  <img src="https://img.shields.io/badge/MCP_tools-42-D4A017?style=flat-square" alt="MCP Tools">
  <img src="https://img.shields.io/badge/docker-3_containers-D4A017?style=flat-square" alt="Docker">
  <img src="https://img.shields.io/badge/version-v1.7.0-D4A017?style=flat-square" alt="Version">
  <img src="https://img.shields.io/badge/license-MIT-D4A017?style=flat-square" alt="License">
</p>

<!-- Boot sequence GIF goes here -->
<!-- ![oikOS Boot Sequence](docs/assets/boot.gif) -->

---

## What is oikOS?

oikOS is the local-first operating system where AI agents live, work, and thrive. Named for the ancient Greek word for "home" — the basic unit of society — oikOS gives your agents a permanent place to live, with persistent memory, a personal knowledge vault, and 42 MCP tools behind a privacy-enforced middleware stack. Bring any model — local via Ollama or cloud via Anthropic, OpenAI, Google, or any OpenAI-compatible API. Your data stays on your machine. Your agents, your home, your rules.

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

## Choose Your Model

oikOS is model-agnostic. Use any local model through Ollama, any cloud provider, or both. oikOS routes queries automatically based on complexity and privacy requirements — sensitive data always stays local.

```bash
# Use any Ollama model (runs locally, free, private)
oikos provider set-default ollama --model llama3.1:8b
oikos provider set-default ollama --model qwen2.5:14b
oikos provider set-default ollama --model mistral:7b

# Or connect a cloud provider
oikos provider set-default anthropic --model claude-sonnet-4-20250514
oikos provider set-default openai --model gpt-4o
oikos provider set-default google --model gemini-2.0-flash

# Or use any OpenAI-compatible API (LM Studio, vLLM, text-generation-webui)
oikos provider set-default generic --model my-model --base-url http://localhost:1234/v1

# Check what's configured
oikos provider list
oikos provider test
```

**How routing works:**
- **Simple queries** → local small model (fast, free)
- **Moderate queries** → local large model (capable, free)
- **Complex queries** → cloud model (when you choose to enable it)
- **Sensitive data** → always local, regardless of complexity. The `NEVER_LEAVE` privacy tier is absolute.

Configure your providers in `providers.toml`:

```toml
[providers.ollama]
enabled = true
base_url = "http://localhost:11434"
default_model = "llama3.1:8b"    # Your choice

[providers.anthropic]
enabled = false                    # Opt-in, not default
api_key_env = "ANTHROPIC_API_KEY"
default_model = "claude-sonnet-4-20250514"

[providers.openai]
enabled = false
api_key_env = "OPENAI_API_KEY"
default_model = "gpt-4o"
```

See `providers.toml.example` for all options.

---

## Local Inference Backends

oikOS doesn't lock you into a single local inference engine. Any backend that exposes an OpenAI-compatible API works out of the box via the `generic` provider. Ollama is the default because it's the easiest to set up, but you can swap it for any of these:

| Backend | Best For | Setup | Config |
|---------|----------|-------|--------|
| [Ollama](https://ollama.com) | Easiest setup. One command. | `ollama serve` | Built-in provider |
| [llama.cpp](https://github.com/ggerganov/llama.cpp) | Maximum single-user performance. CPU/CUDA/Vulkan/Metal. | `llama-server -m model.gguf` | Generic provider |
| [LM Studio](https://lmstudio.ai) | GUI-based model management. Multiple backends. | Download + run | Generic provider |
| [vLLM](https://github.com/vllm-project/vllm) | Production multi-user serving. PagedAttention. | `vllm serve model` | Generic provider |
| [SGLang](https://github.com/sgl-project/sglang) | Highest throughput. RadixAttention. Structured output. | `python -m sglang.launch_server` | Generic provider |
| [ExLlamaV2](https://github.com/turboderp/exllamav2) / [ExLlamaV3](https://github.com/turboderp/exllamav3) | Best NVIDIA performance. Custom quantization (EXL2/EXL3). | Python library + TabbyAPI | Generic provider |
| [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM) | Maximum NVIDIA throughput at scale. | Complex setup | Generic provider |
| [LocalAI](https://localai.io) | Most format support. Multiple backends. | `docker run localai` | Generic provider |
| [Jan](https://jan.ai) | Privacy-focused desktop app. | Download + run | Generic provider |

### Example: Using llama.cpp instead of Ollama

```bash
# Start llama.cpp server
llama-server -m ~/models/llama-3.1-8b-q4_k_m.gguf --port 8080 --host 0.0.0.0

# Configure oikOS to use it
oikos provider set-default generic --model llama-3.1-8b --base-url http://localhost:8080/v1
```

### Example: Using vLLM

```bash
# Start vLLM server
vllm serve meta-llama/Llama-3.1-8B-Instruct --port 8000

# Configure oikOS
oikos provider set-default generic --model Llama-3.1-8B-Instruct --base-url http://localhost:8000/v1
```

### Example: Using LM Studio

```bash
# Start LM Studio, load a model, enable local server (port 1234 by default)

# Configure oikOS
oikos provider set-default generic --model my-model --base-url http://localhost:1234/v1
```

### Example: Using SGLang

```bash
# Start SGLang server
python -m sglang.launch_server --model-path meta-llama/Llama-3.1-8B-Instruct --port 30000

# Configure oikOS
oikos provider set-default generic --model Llama-3.1-8B-Instruct --base-url http://localhost:30000/v1
```

### Example: Using ExLlamaV2/V3 (via TabbyAPI)

```bash
# Start TabbyAPI with ExLlamaV2/V3 backend
python main.py --model-dir ~/models/llama-3.1-8b-exl2 --port 5000

# Configure oikOS
oikos provider set-default generic --model llama-3.1-8b --base-url http://localhost:5000/v1
```

Any server that speaks the OpenAI `/v1/chat/completions` protocol works. oikOS doesn't care what's underneath — it cares about your privacy, your autonomy rules, and your vault.

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

**Inference:**
* **Any local backend** — [Ollama](https://ollama.com) (default), [llama.cpp](https://github.com/ggerganov/llama.cpp), [LM Studio](https://lmstudio.ai), [vLLM](https://github.com/vllm-project/vllm), [SGLang](https://github.com/sgl-project/sglang), [ExLlamaV2/V3](https://github.com/turboderp/exllamav2), [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM), [LocalAI](https://localai.io), [Jan](https://jan.ai)
* **Any cloud provider** — [Anthropic](https://anthropic.com), [OpenAI](https://openai.com), [Google](https://ai.google), or any OpenAI-compatible API

**Core:**
* **Python 3.12+** — primary language
* **LanceDB** — embedded vector database (no server required)
* **FastAPI** — REST API + WebSocket server
* **MCP SDK** — Model Context Protocol (works with Claude Desktop, Claude Code, and any MCP client)

**Web & Research:**
* **Playwright** — headless browser automation (on-demand)
* **SearXNG** — self-hosted sovereign search (Docker, zero telemetry)

**Frontend:**
* **React 19 + Vite 6** — dashboard UI

**Deployment:**
* **Docker Compose** — 3-container sovereign stack

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
