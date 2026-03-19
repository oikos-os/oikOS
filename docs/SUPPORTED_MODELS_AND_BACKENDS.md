# Supported Models and Backends

oikOS works with any LLM through two mechanisms:
1. **Named providers** — first-class integrations with Ollama, Anthropic, OpenAI, and Google
2. **Generic provider** — any server that speaks the OpenAI /v1/chat/completions protocol

## Local Backends

| Backend | Protocol | GPU Support | Setup Effort | Best For |
|---------|----------|-------------|-------------|----------|
| Ollama | OpenAI-compat | CUDA, Metal, ROCm | Minimal | Getting started, single-user |
| llama.cpp | OpenAI-compat | CUDA, Metal, Vulkan, ROCm, CPU | Low | Maximum performance, any hardware |
| LM Studio | OpenAI-compat | CUDA, Metal, Vulkan | Minimal (GUI) | Non-CLI users, model exploration |
| vLLM | OpenAI-compat | CUDA, ROCm | Moderate | Multi-user serving, production |
| SGLang | OpenAI-compat | CUDA | Moderate | Highest throughput, structured output |
| ExLlamaV2/V3 | OpenAI-compat (via TabbyAPI) | CUDA | Moderate | Best NVIDIA performance, custom quants |
| TensorRT-LLM | OpenAI-compat (via Triton) | CUDA (TensorRT) | High | Maximum NVIDIA throughput at scale |
| LocalAI | OpenAI-compat | CUDA, Metal, CPU | Low (Docker) | Most format support |
| Jan | OpenAI-compat | CUDA, Metal, Vulkan | Minimal (GUI) | Privacy-focused desktop |

## Cloud Providers

| Provider | Models | Config Key |
|----------|--------|------------|
| Anthropic | Claude Opus, Sonnet, Haiku | `ANTHROPIC_API_KEY` |
| OpenAI | GPT-4o, GPT-4, o1, o3 | `OPENAI_API_KEY` |
| Google | Gemini 2.0 Flash, Pro | `GOOGLE_API_KEY` |
| Any OpenAI-compatible | Groq, Together, Fireworks, Cerebras, etc. | `GENERIC_API_KEY` + `base_url` |

## Popular Local Models

| Model | Parameters | VRAM (Q4) | Good For |
|-------|-----------|-----------|----------|
| Llama 3.1 8B | 8B | ~5 GB | Fast, general purpose |
| Qwen 2.5 14B | 14B | ~9 GB | Strong reasoning |
| Mistral 7B | 7B | ~4.5 GB | Fast instruction following |
| DeepSeek R1 14B | 14B | ~9 GB | Reasoning, code |
| Phi-3 14B | 14B | ~9 GB | Compact, capable |
| Llama 3.1 70B | 70B | ~40 GB | Frontier-class local |
| Codellama 13B | 13B | ~8 GB | Code-focused |
| Command R+ | 104B | ~60 GB | RAG-optimized |

## Privacy Behavior

Regardless of which backend or provider you use:
- **NEVER_LEAVE** content is ONLY processed by local backends (localhost)
- **SENSITIVE** content is PII-scrubbed before cloud routing
- **SAFE** content can go anywhere

The ContentClassifier enforces this on every tool call and every inference request. No exceptions.

## How to Switch Backends

```bash
# Check current configuration
oikos provider list

# Switch to a different local backend
oikos provider set-default generic --model my-model --base-url http://localhost:PORT/v1

# Test the connection
oikos provider test

# Switch back to Ollama
oikos provider set-default ollama --model llama3.1:8b
```
