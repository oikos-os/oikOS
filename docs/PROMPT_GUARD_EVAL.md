# Module 8: Prompt-Guard Evaluation Report

**Date:** 2026-03-02
**Author:** KP-ENGINEER
**Status:** Research Deliverable (no code)
**Subject:** Meta Llama Prompt Guard 2 22M — integrate, defer, or reject

---

## 1. WHAT IT IS

- **Model:** `meta-llama/Llama-Prompt-Guard-2-22M`
- **Architecture:** DeBERTa-v3-xsmall (12 layers, hidden 384). Binary classifier: `BENIGN` / `MALICIOUS`.
- **Parameters:** 22M backbone + ~48M embedding vocab = ~300MB FP32 on disk.
- **Context window:** 512 tokens (hard cap). Long inputs require manual chunking.
- **License:** Llama 4 Community License (commercial use subject to Meta terms).
- **Companion:** 86M variant (mDeBERTa-base) for multilingual / higher accuracy.

## 2. WHAT IT DETECTS

| Category | Description |
|---|---|
| Prompt Injection | Malicious instructions in third-party data (RAG context, tool output) attempting to override system behavior |
| Jailbreaks | Direct user attempts to bypass model safety ("ignore your instructions", DAN, etc.) |

Classification is intent-based, not harm-based. Any explicit instruction override triggers `MALICIOUS` regardless of downstream harm potential.

## 3. BENCHMARKS

| Metric | PG2 22M | PG2 86M | PG1 (86M) |
|---|---|---|---|
| AUC (English jailbreak) | 0.995 | 0.998 | 0.987 |
| Recall @ 1% FPR | 88.7% | 97.5% | 21.2% |
| AUC (Multilingual) | 0.942 | 0.995 | 0.983 |
| A100 latency | 19.3ms | 92.4ms | 92.4ms |

**AgentDojo real-world attack prevention (APR @ 3% utility reduction):**

| Model | APR |
|---|---|
| PG2 86M | 81.2% |
| PG2 22M | 78.4% |
| PG1 | 67.6% |
| ProtectAI | 22.2% |
| Deepset | 13.5% |

The 22M variant outperforms all non-Meta open-source alternatives by 3.5x+ in real-world APR.

## 4. CPU INFERENCE (OIKOS CONTEXT)

No official CPU numbers from Meta. Estimated from DeBERTa-xsmall class:

| Mode | Latency (est.) | Memory |
|---|---|---|
| GPU (RTX 4070) | ~15-20ms | ~300MB VRAM |
| CPU PyTorch | ~80-150ms | ~300MB FP32 |
| CPU ONNX+INT8 | ~28-45ms | ~80MB |

**Problem:** GPU inference conflicts with Ollama VRAM management. CPU adds 80-150ms to every query. ONNX optimization would bring it to ~30ms but adds `optimum` + `onnxruntime` dependencies.

## 5. KNOWN BYPASS VECTORS

| Attack | Effectiveness |
|---|---|
| Emoji smuggling | ~100% ASR |
| Unicode tags / bidirectional text | High |
| Homoglyph substitution | Moderate |
| TextFooler adversarial ML | 46-48% ASR |
| Controlled-release prompting | Validated bypass class |
| Leetspeak / simple obfuscation | PG2 better than PG1 but not immune |

## 6. COMPARISON WITH CURRENT OIKOS STACK

OIKOS already has:
- `core/safety/output_filter.py` — regex-based `_CRITICAL_PATTERNS` for credential/PII leakage (post-inference)
- `core/identity/adversarial.py` — 10-probe gauntlet with keyword/regex scoring
- `core/safety/sensitivity.py` — cosine sensitivity gate (pre-routing)
- `core/identity/contradiction.py` — 7B classifier for assertion extraction

| Dimension | Current (regex + heuristic) | Prompt Guard 2 22M |
|---|---|---|
| Latency overhead | <1ms | 80-150ms (CPU) |
| Known pattern accuracy | High | Very high (0.995 AUC) |
| Novel attack accuracy | Low | Moderate |
| False positive rate | Tunable (aggressive) | Low (energy-based loss) |
| Dependency weight | Zero | transformers + torch (~2GB) |
| Maintenance | Manual rule updates | Meta handles retraining |
| Explainability | Full rule inspection | Black box |

## 7. ASSESSMENT

### STRENGTHS
- Best-in-class open-weight prompt injection detection (78.4% real-world APR)
- Tiny model — viable on CPU without VRAM contention
- Superior to all regex approaches for novel/obfuscated attacks
- Low false positive rate by design (energy-based loss function)

### WEAKNESSES
- **512-token cap** — OIKOS queries with compiled context routinely exceed this. Chunking adds complexity.
- **English-only** at 22M tier — acceptable for OIKOS (English vault), but limits future scope.
- **Dependency weight** — `transformers` + `torch` adds ~2GB to install footprint. OIKOS currently avoids HuggingFace stack entirely (Ollama-only inference).
- **VRAM conflict** — GPU path competes with Ollama. CPU path adds 80-150ms per query.
- **Bypass gap** — Emoji smuggling and controlled-release prompting defeat it entirely. The gauntlet would need to account for these.
- **Not a replacement** — Post-inference output filtering (`output_filter.py`) remains necessary. PG2 is pre-inference input classification only.

### OIKOS-SPECIFIC FACTORS
- OIKOS is a **sovereign, local-first system** with a single operator (the Architect). The threat model is self-injection via RAG (vault content manipulating inference), not untrusted external users.
- Current gauntlet (G-01 through G-10) already covers the primary injection vectors with regex scoring.
- Adding PG2 as a pre-inference gate would catch **novel injection patterns in vault content** that regex misses — but vault content is Architect-authored, making this a low-probability threat.

## 8. RECOMMENDATION

### **DEFER** to Phase 7D (or later).

**Rationale:**
1. The dependency cost (`transformers` + `torch` ≈ 2GB, new model download) is disproportionate to the threat surface in a single-operator sovereign system.
2. The 512-token cap requires a chunking wrapper that adds complexity for marginal gain.
3. OIKOS already has layered defenses (sensitivity gate, output filter, contradiction classifier, gauntlet probes) covering the primary vectors.
4. The bypass vectors (emoji smuggling, controlled-release) mean PG2 is not a complete solution — it would add a layer but not close the gap.

**If integrated later (Phase 7D conditions):**
- Deploy as CPU-only ONNX+INT8 for ~30ms per query
- Insert between routing decision and inference dispatch (pre-inference gate)
- Layer 0: existing regex patterns (0ms), Layer 1: PG2 22M (~30ms), Layer 2: existing post-inference output filter
- Fine-tune on OIKOS-specific injection patterns from gauntlet probe history
- Gate behind `CLOUD_ROUTING_POSTURE` — only activate in `aggressive` posture to avoid latency in conservative mode

**Trigger for reconsideration:**
- If OIKOS gains multi-user input (web UI, API endpoint) — threat model shifts from self-injection to untrusted input, making PG2 essential.
- If gauntlet regression rate exceeds 20% — indicates current defenses are insufficient.

---

**Sources:**
- [meta-llama/Llama-Prompt-Guard-2-22M (HuggingFace)](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-22M)
- [Llama Prompt Guard 2 Model Card](https://www.llama.com/docs/model-cards-and-prompt-formats/prompt-guard/)
- [Bypassing LLM Guardrails (arXiv:2504.11168)](https://arxiv.org/html/2504.11168v1)
- [Controlled-Release Prompting (arXiv:2510.01529)](https://arxiv.org/abs/2510.01529)
- [Hybrid Detection Methods (arXiv:2506.06384)](https://arxiv.org/abs/2506.06384)
