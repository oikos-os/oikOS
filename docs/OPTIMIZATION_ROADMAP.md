# oikOS Token Optimization Roadmap
**Maintained by:** KP-ENGINEER
**Last updated:** 2026-03-15
**Doctrine:** "Intelligence is cheap. Context is expensive. Build for context."

---

## Shipped Optimizations

| Optimization | Impact | Module |
|---|---|---|
| Context Engine (observation masking, tool compression, budget tracker) | 71.4% token reduction | `core/agency/context_engine.py`, `compressor.py`, `budget.py` |
| ReWOO Planner | O(1) vs O(N^2) context growth | `core/agency/planner.py` |
| Hybrid Search (BM25 + vector) | Only relevant chunks loaded, not entire documents | `core/memory/search.py` |
| Tiered Memory | Budget-controlled per tier, episodic decay | `core/memory/indexer.py` |
| Multi-Provider Routing | Right model for the job (local free, cloud paid, privacy-sensitive always local) | `core/cognition/providers/router.py` |
| Content Classification | NEVER_LEAVE patterns force local routing — no cloud cost for sensitive queries | `core/cognition/providers/content_classifier.py` |

---

## Planned Optimizations

| ID | Enhancement | Description | Depends On | Status |
|---|---|---|---|---|
| OPT-01 | Adaptive model selection | Auto-choose model size by query complexity. Simple -> 7B. Complex reasoning -> 14B. Cloud-grade -> provider router. Classify query difficulty BEFORE inference. | T-047 (providers.toml) | PLANNED |
| OPT-02 | Speculative inference | Start with local 7B. Check confidence score. If below threshold, re-run on 14B or escalate to cloud. Only pay for cloud when local can't handle it. Net effect: 80%+ of queries stay free. | T-047 + OPT-01 | PLANNED |
| OPT-03 | Context caching | Cache compiled context windows keyed on (vault hash + query topic). Same vault state + same topic = skip recompilation. Invalidate on vault index change. | Phase 8 | PLANNED |
| OPT-04 | Streaming compression | Compress multi-turn conversation history as it grows. Summarize older turns, keep recent turns full. Reduces token count for follow-up queries in long sessions. | Phase 8 | PLANNED |
| OPT-05 | Web content compression | Readability extraction strips HTML to clean text (97% reduction). Applied before content enters context window. Integrated with Phase 7e browser module. | Phase 7e | PLANNED |
| OPT-06 | Provider cost tracking | Per-query cost estimation and logging. Dashboard shows token spend by provider, by day, by query type. Users see exactly what they're paying. | T-047 | PLANNED |

---

## Implementation Priority

```
T-047 (providers.toml)
  ├── OPT-01: Adaptive model selection (build into routing logic)
  ├── OPT-06: Provider cost tracking (build into response pipeline)
  └── OPT-02: Speculative inference (after T-047 + OPT-01 validate)

Phase 7e (The Eyes)
  └── OPT-05: Web content compression (readability extraction)

Phase 8
  ├── OPT-03: Context caching
  └── OPT-04: Streaming compression
```

OPT-01 and OPT-06 are natural extensions of T-047's `providers.toml` infrastructure and should be implemented alongside it, not as separate tasks.

---

## Hardware Optimization

| ID | Enhancement | Description | Status |
|---|---|---|---|
| HW-01 | RTX 5070 Ti acquisition | Replace 4070 as primary GPU in SIGMA-01. Gaming + ComfyUI rendering. 16GB VRAM. | DECISION PENDING |
| HW-02 | Dedicated AI server (SIGMA-03) | Repurpose RTX 4070 into small-form-factor server. Runs Ollama, ORACLE agents, oikOS daemon, ChromaDB, SearXNG 24/7. AMD Ryzen 5 5600 + 32GB DDR4. ~$380 build. | DECISION PENDING |
| HW-03 | GPU Watchdog retirement | Once dual-machine setup is live, GPU Watchdog becomes unnecessary. Gaming and AI never share hardware again. | AFTER HW-01 + HW-02 |
