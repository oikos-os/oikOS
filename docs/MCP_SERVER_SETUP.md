# oikOS MCP Server Setup
**Phase:** 7e Module 0+1
**Last Updated:** 2026-03-16

---

## Quick Start

```bash
# Start MCP server (stdio for Claude Desktop / Claude Code)
python -m core.framework --transport stdio --toolsets vault,system,file
```

---

## Claude Desktop Configuration

**File:** `C:\Users\arodr\AppData\Roaming\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "oikos": {
      "command": "D:\\Development\\OIKOS_OMEGA\\.venv\\Scripts\\python.exe",
      "args": ["-m", "core.framework", "--transport", "stdio", "--toolsets", "vault,system,file"]
    }
  }
}
```

Restart Claude Desktop after editing.

---

## Claude Code Configuration

**File:** `D:\Development\OIKOS_OMEGA\.mcp.json` (project-scoped)

```json
{
  "mcpServers": {
    "oikos-framework": {
      "type": "stdio",
      "command": "D:\\Development\\OIKOS_OMEGA\\.venv\\Scripts\\python.exe",
      "args": ["-m", "core.framework", "--transport", "stdio", "--toolsets", "vault,system,file"]
    }
  }
}
```

Verify: `claude mcp list`

---

## Available Toolsets

| Toolset | Tools | Use Case |
|---|---|---|
| `vault` | vault.search, vault.compile, vault.index | Vault search and context compilation |
| `system` | system.status, state.get, state.transition, gauntlet.run, session.start, session.close, ollama.generate, provider.query | System management and inference |
| `file` | fs.read, fs.list, fs.search, fs.write, fs.edit | Scoped filesystem operations |

### Filtering Toolsets

Only expose what the client needs:

```bash
# Vault only (3 tools, 267 tokens)
python -m core.framework --transport stdio --toolsets vault

# Vault + System (11 tools, 656 tokens)
python -m core.framework --transport stdio --toolsets vault,system

# All toolsets (16 tools, 1,408 tokens)
python -m core.framework --transport stdio --toolsets vault,system,file
```

---

## Token Savings vs Baseline

| Configuration | Tools | Schema Tokens | Savings vs Baseline |
|---|---|---|---|
| Windows-MCP + Desktop Commander | ~50 | ~6,500 (estimated) | — |
| oikOS (all toolsets) | 16 | 1,408 | 78% |
| oikOS (vault+system) | 11 | 656 | 90% |
| oikOS (vault only) | 3 | 267 | 96% |

---

## Adding New Tools

```python
from core.framework import oikos_tool, PrivacyTier, AutonomyLevel

@oikos_tool(
    name="oikos.custom.my_tool",
    description="What this tool does",
    privacy=PrivacyTier.SAFE,        # NEVER_LEAVE | SENSITIVE | SAFE
    autonomy=AutonomyLevel.SAFE,     # SAFE | ASK_FIRST | PROHIBITED
    toolset="system",                # vault | system | file | browser | research
    cost_category="local",           # local | cloud | api
    rate_limit=10,                   # calls/min (0 = unlimited)
)
def my_tool(query: str, limit: int = 5) -> dict:
    # Business logic here. Function remains directly callable.
    return {"result": "data"}
```

Import the module in `core/framework/tools/__init__.py` to trigger registration at startup.

---

## Privacy Tiers

| Tier | Input | Output | Enforcement |
|---|---|---|---|
| NEVER_LEAVE | Blocked on remote transport | Redacted from response + audit log | Mandatory, cannot disable |
| SENSITIVE | Anonymized before cloud | Deanonymized in response | Mandatory |
| SAFE | Pass through | Pass through | — |

---

## Autonomy Levels

| Level | Behavior |
|---|---|
| SAFE | Executes immediately |
| ASK_FIRST | Creates approval proposal, raises ApprovalRequired |
| PROHIBITED | Raises PermissionError |

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Server won't start | Check `.venv` activation: `source .venv/Scripts/activate` |
| "Module not found" | Run from project root: `cd D:\Development\OIKOS_OMEGA` |
| Tools not appearing | Import module in `core/framework/tools/__init__.py` |
| Claude Desktop not connecting | Restart Claude Desktop after config change |
| Permission denied on file ops | FileAgent scope: only SIGMA_VAULT (READ), COMMAND/staging+messages (READ_WRITE) |
| "Tool error: ConnectionError" | Ollama not running. Start with `ollama serve` |
