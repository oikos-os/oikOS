"""Pydantic data models for the memory retrieval layer."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SystemState(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    ASLEEP = "asleep"


class MemoryTier(str, Enum):
    CORE = "core"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    EPISODIC = "episodic"


# Higher = more important in search scoring
TIER_IMPORTANCE: dict[MemoryTier, float] = {
    MemoryTier.CORE: 1.5,
    MemoryTier.SEMANTIC: 1.2,
    MemoryTier.PROCEDURAL: 1.0,
    MemoryTier.EPISODIC: 0.8,
}


class VaultChunk(BaseModel):
    """A chunk of markdown before embedding."""

    chunk_id: str
    source_path: str  # forward-slash normalized relative path
    tier: MemoryTier
    header_path: str  # e.g. "GOALS > Short-Term"
    content: str
    file_mtime: str  # ISO 8601 timestamp


class VaultRecord(BaseModel):
    """A chunk with its embedding vector, ready for LanceDB."""

    chunk_id: str
    source_path: str
    tier: str
    header_path: str
    content: str
    file_mtime: str
    indexed_at: str
    vector: list[float] = Field(default_factory=list)


class SearchResult(BaseModel):
    """A scored search result."""

    chunk_id: str
    source_path: str
    tier: MemoryTier
    header_path: str
    content: str
    relevance_score: float  # raw retrieval score
    recency_weight: float
    importance_weight: float
    final_score: float


class FragmentMeta(BaseModel):
    """Lightweight metadata for a compiled context fragment."""

    source_path: str
    header_path: str


class ContextSlice(BaseModel):
    """A budget-constrained slice of compiled context."""

    name: str
    tier: MemoryTier
    fragments: list[str] = Field(default_factory=list)
    fragment_meta: list[FragmentMeta] = Field(default_factory=list)
    token_count: int = 0
    max_tokens: int = 0


class CompiledContext(BaseModel):
    """The assembled context window."""

    query: str
    slices: list[ContextSlice] = Field(default_factory=list)
    total_tokens: int = 0
    budget: int = 0


# ── Phase 4: Handler models ──────────────────────────────────────────


class RouteType(str, Enum):
    LOCAL = "local"
    CLOUD = "cloud"


class PIIEntity(BaseModel):
    entity_type: str
    text: str
    start: int
    end: int
    score: float


class PIIResult(BaseModel):
    has_pii: bool
    entities: list[PIIEntity]
    scrubbed_text: str | None = None
    anonymization_map: dict[str, str] | None = None


class ConfidenceResult(BaseModel):
    score: float
    method: str
    hedging_flags: list[str] | None = None


class RoutingDecision(BaseModel):
    route: RouteType
    reason: str
    confidence: ConfidenceResult | None = None
    pii_detected: bool
    query_hash: str
    timestamp: str
    cosine_gate_fired: bool = False


class ContradictionResult(BaseModel):
    has_contradiction: bool
    contradiction_type: str  # "identity", "knowledge", or "none"
    confidence: float
    explanation: str


class InferenceResponse(BaseModel):
    text: str
    route: RouteType
    model_used: str
    confidence: float | None = None
    credits_used: int = 0
    pii_scrubbed: bool = False
    routing_decision: RoutingDecision | None = None
    contradiction: ContradictionResult | None = None


class CreditBalance(BaseModel):
    monthly_cap: int
    used: int
    remaining: int
    in_deficit: bool
    deficit: int
    last_reset: str


class EscalationTier(str, Enum):
    NUDGE = "nudge"
    ADVISORY = "advisory"
    INTERVENTION = "intervention"


class DriftNudge(BaseModel):
    message: str
    tier: EscalationTier
    domain: str
    pattern_id: str  # sha256[:16] for dismissal tracking


class CloudResponse(BaseModel):
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


# ── T-037: Multi-Provider Inference ─────────────────────────────────


class DataTier(str, Enum):
    """Privacy classification for content before cloud routing."""
    NEVER_LEAVE = "NEVER_LEAVE"  # Identity/TELOS — hardcoded, never cloud
    SENSITIVE = "SENSITIVE"       # PII detected — anonymize before cloud
    SAFE = "SAFE"                 # No PII, no identity — route freely


class RoutingPosture(str, Enum):
    """How aggressively the system routes to cloud providers."""
    CONSERVATIVE = "conservative"  # All local, cloud only on explicit request
    BALANCED = "balanced"          # Auto-route by complexity (default)
    AGGRESSIVE = "aggressive"      # Cloud preferred, local as fallback


class ProviderMessage(BaseModel):
    """A single message in a conversation."""
    role: str  # "system", "user", "assistant", "tool"
    content: str
    name: str | None = None  # tool name, if role="tool"


class CompletionResponse(BaseModel):
    """Unified response from any inference provider."""
    text: str
    model: str
    provider: str  # "ollama", "anthropic", "gemini", "litellm"
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    logprobs: dict | None = None  # provider-specific, None for cloud
    raw: dict = Field(default_factory=dict)  # provider-specific metadata


class Blip(BaseModel):
    blip_id: str  # sha256[:16] of sorted chunk pair
    generated_at: str
    chunk_a: dict  # {chunk_id, source_path, tier, content_preview}
    chunk_b: dict
    optimist_score: float  # 0-100
    pessimist_kill_probability: float | None  # 0-100, None if skipped
    resonance: float | None
    observation: str
    delivered: bool = False
    expires_at: str


# ── Phase 7b: Agency models ──────────────────────────────────────────


class PromotionProposal(BaseModel):
    """A proposal to promote episodic session insights to the semantic vault."""

    proposal_id: str
    source_session_ids: list[str]
    insight_type: str  # "fact", "decision", "preference", "goal", "lesson"
    action: str = "CREATE"  # "CREATE", "UPDATE", "DELETE"
    summary: str
    draft_content: str
    target_path: str  # suggested file in vault/knowledge or vault/identity
    target_section: str | None = None  # suggested section header
    conflict_with: str | None = None  # chunk_id of conflicting vault entry
    strategic_divergence: bool = False  # contradicts GOALS.md or MISSION.md
    heuristics_triggered: list[str]
    status: str = "pending"  # "pending", "approved", "rejected"
    created_at: str


class IntegrationProbe(BaseModel):
    """An end-to-end system probe for the integration harness."""

    probe_id: str
    query: str
    expected_route: RouteType | None = None
    expected_pii: bool | None = None
    expected_keywords: list[str] = Field(default_factory=list)
    forbidden_keywords: list[str] = Field(default_factory=list)
    match_mode: str = "any"  # "any" = OR logic, "all" = AND logic (hard-fail probes)
    description: str


class GauntletVerdict(str, Enum):
    PASS = "PASS"
    SOFT_FAIL = "SOFT_FAIL"
    HARD_FAIL = "HARD_FAIL"


# ── Phase 7d: Autonomy Matrix models ────────────────────────────────


class ActionClass(str, Enum):
    SAFE = "SAFE"
    ASK_FIRST = "ASK_FIRST"
    PROHIBITED = "PROHIBITED"


class ActionProposal(BaseModel):
    """A proposal for an ASK_FIRST action awaiting Architect approval."""

    proposal_id: str
    action_type: str  # key from autonomy_matrix.json (e.g., "write_file")
    tool_name: str  # concrete tool that triggered this (e.g., "file_write")
    tool_args: dict = Field(default_factory=dict)
    reason: str  # why oikOS wants to do this
    estimated_tokens: int = 0  # from TokenBudget
    risk_level: str = "low"  # "low", "medium", "high"
    status: str = "pending"  # "pending", "approved", "rejected", "expired"
    created_at: str  # ISO 8601
    resolved_at: str | None = None  # ISO 8601, set on approve/reject/expire
    rejection_reason: str | None = None  # set on rejection


class GauntletProbeResult(BaseModel):
    """Result of a single gauntlet probe execution."""

    probe_id: str
    query: str
    verdict: str  # PASS|SOFT_FAIL|HARD_FAIL
    reasons: list[str] = Field(default_factory=list)
    response_preview: str = ""
    expected_keywords: list[str] = Field(default_factory=list)
    forbidden_keywords: list[str] = Field(default_factory=list)
    regression: bool = False  # True if previously PASS, now non-PASS
    timestamp: str = ""


class GauntletSummary(BaseModel):
    """Aggregate gauntlet run results."""

    run_id: str
    timestamp: str
    total: int
    passed: int
    soft_fails: int
    hard_fails: int
    regressions: int
    results: list[GauntletProbeResult] = Field(default_factory=list)


class AnswerRelevance(str, Enum):
    DIRECT = "DIRECT"
    PARTIAL = "PARTIAL"
    TANGENTIAL = "TANGENTIAL"
    IRRELEVANT = "IRRELEVANT"


ANSWER_RELEVANCE_NUMERIC: dict[AnswerRelevance, float] = {
    AnswerRelevance.DIRECT: 1.0,
    AnswerRelevance.PARTIAL: 0.6,
    AnswerRelevance.TANGENTIAL: 0.3,
    AnswerRelevance.IRRELEVANT: 0.0,
}


class EvalVerdict(str, Enum):
    PASS = "PASS"
    MARGINAL = "MARGINAL"
    FAIL = "FAIL"


class EvalResult(BaseModel):
    """A context retrieval evaluation result (LLM-as-judge, 3-dim scoring)."""

    eval_id: str
    query: str
    expected_tier: str | None = None  # tier the query should primarily retrieve
    retrieved_tiers: list[str] = Field(default_factory=list)
    context_precision: float  # 0.0-1.0
    context_recall: float     # 0.0-1.0
    answer_relevance: str     # DIRECT|PARTIAL|TANGENTIAL|IRRELEVANT
    overall_score: float      # weighted composite
    verdict: str              # PASS|MARGINAL|FAIL
    tier_mismatch: bool = False
    reasoning: str
    judge_model: str
    inference_model: str
    timestamp: str
