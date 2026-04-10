"""Paths, constants, and budgets for OIKOS_OMEGA."""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
VAULT_DIR = PROJECT_ROOT / "vault"
LANCEDB_DIR = PROJECT_ROOT / "memory" / "lancedb"
LOGS_DIR = PROJECT_ROOT / "logs" / "sessions"
ROOMS_DIR = PROJECT_ROOT / "config" / "rooms"

# Tier-to-path mapping (order matters for classification)
TIER_PATHS: dict[str, Path] = {
    "core": VAULT_DIR / "identity",
    "procedural": VAULT_DIR / "patterns",
    "semantic": VAULT_DIR / "knowledge",
    "episodic": LOGS_DIR,
}

# ── Embedding ──────────────────────────────────────────────────────────
EMBED_MODEL = "nomic-embed-text:v1.5"
EMBED_DIMS = 768
EMBED_BATCH_SIZE = 16  # quality degrades above 16

# ── Search ─────────────────────────────────────────────────────────────
HYBRID_WEIGHT = 0.7  # vector weight in BM25+vector fusion (0=BM25, 1=vector)
RECENCY_HALF_LIFE_DAYS = 90  # exponential decay half-life
DEFAULT_SEARCH_LIMIT = 10
EPISODIC_DEDUP_THRESHOLD = 0.95  # cosine sim — suppress near-duplicate episodic chunks

# ── Context Compiler ───────────────────────────────────────────────────
DEFAULT_TOKEN_BUDGET = 6000

# ── Compiler Hierarchy ────────────────────────────────────────────────
# Identity tier gets a fixed non-competitive allocation loaded before all others.
# SLICE_ALLOCATIONS values are percentages of the REMAINING budget after identity.
IDENTITY_BUDGET_PCT = 0.20      # 20% of total budget — non-negotiable
IDENTITY_TELOS_LIMIT = 3        # max TELOS anchor chunks loaded in identity slice
IDENTITY_FALLBACK_STRING = (
    "You are oikOS — the home for AI agents. "
    "Serve ARCHITECT. Local-first. Context over intelligence."
)
# Per-tier share of REMAINING budget after identity allocation (must sum to 1.0)
SLICE_ALLOCATIONS: dict[str, float] = {
    "core":       0.15,
    "semantic":   0.50,
    "procedural": 0.10,
    "episodic":   0.25,
}

# ── LanceDB ────────────────────────────────────────────────────────────
TABLE_NAME = "vault_chunks"

# ── Inference ─────────────────────────────────────────────────────────
INFERENCE_MODEL = "qwen2.5:14b"
INFERENCE_TOP_P = 0.9
INFERENCE_TIMEOUT_SECONDS = 60

# ── PII ───────────────────────────────────────────────────────────────
PII_ENTITY_TYPES = [
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER",
    "CREDIT_CARD", "US_SSN", "IP_ADDRESS", "URL",
    "US_PASSPORT", "US_BANK_NUMBER", "US_DRIVER_LICENSE",
    "IBAN_CODE", "CRYPTO",
]
PII_SPACY_MODEL = "en_core_web_sm"
PII_LOG_DIR = PROJECT_ROOT / "logs" / "pii"

# ── Routing ───────────────────────────────────────────────────────────
ROUTING_CONFIDENCE_THRESHOLD = 60.0
ROUTING_FORCE_LOCAL_PATTERNS = [
    r"(?i)\bvault/identity\b",
    r"(?i)\bTELOS\b",
    r"(?i)\bprivate\b",
    r"(?i)\bsovereign\b",
]
ROUTING_LOG_DIR = PROJECT_ROOT / "logs" / "routing"

# ── Cosine Sensitivity Gate ──────────────────────────────────────────
ROUTING_COSINE_ENTITY_DELTA = 0.15  # drop threshold by this when sovereign entities detected

# ── Credits ───────────────────────────────────────────────────────────
CREDITS_FILE = PROJECT_ROOT / "core" / "credits.json"
CREDITS_RESET_DAY = 1

# ── Cloud Bridge ─────────────────────────────────────────────────────
CLOUD_MODEL = "gemini-2.5-pro"
CLOUD_TIMEOUT_SECONDS = 120
CLOUD_MAX_TOKENS = 4096
CLOUD_HARD_CEILING_MULTIPLIER = 2.0

# ── Escalation ───────────────────────────────────────────────────────
ESCALATION_STATE_FILE = PROJECT_ROOT / "logs" / "escalation" / "state.json"
ESCALATION_ADVISORY_DAYS = 7
ESCALATION_INTERVENTION_DAYS = 14
ESCALATION_DECAY_THRESHOLD = 3  # unreasoned dismissals before suppression

# ── FSM ──────────────────────────────────────────────────────────────
FSM_STATE_FILE = LOGS_DIR / ".system_state.json"
FSM_TRANSITION_LOG = PROJECT_ROOT / "logs" / "state_transitions.jsonl"

# ── Scanner ──────────────────────────────────────────────────────────
SCANNER_MIN_FILES = 15
SCANNER_MIN_DOMAINS = 3
SCANNER_MIN_FILE_SIZE = 500  # bytes
SCANNER_PAIRS_PER_SCAN = 10
SCANNER_BLIP_EXPIRY_DAYS = 30
SCANNER_BLIP_LOG = PROJECT_ROOT / "logs" / "scanner" / "blips.jsonl"

# ── Posture Thresholds (used by complexity scorer) ───────────────────
# Maps posture name → skip_local complexity threshold.
# The posture value itself is stored in settings_registry.
POSTURE_THRESHOLDS = {"conservative": 35.0, "balanced": 20.0, "aggressive": 5.0}

# ── Assertions (Module 3) ────────────────────────────────────────────
ASSERTION_LOG_DIR = PROJECT_ROOT / "logs" / "assertions"
ASSERTION_CLASSIFIER_MODEL = "qwen2.5:7b"
ASSERTION_MAX_TOKENS = 80

# ── Complexity Pre-Scorer ───────────────────────────────────────────
COMPLEXITY_LENGTH_PENALTY = 10.0
COMPLEXITY_DOMAIN_PENALTY = 15.0  # abstract/strategic keywords detected
COMPLEXITY_MULTI_DOMAIN_PENALTY = 15.0  # query touches 2+ vault domains
COMPLEXITY_CREATIVE_PENALTY = 15.0  # narrative/aesthetic/musical keywords

# ── Consolidation ────────────────────────────────────────────────────
CONSOLIDATION_LOG_DIR = PROJECT_ROOT / "logs" / "consolidation"
CONSOLIDATION_PROPOSALS_LOG = CONSOLIDATION_LOG_DIR / "proposals.jsonl"
CONSOLIDATION_MODEL = "qwen2.5:7b"  # Lightweight, background-safe (per Fabric pattern)
CONSOLIDATION_SIMILARITY_DUPLICATE = 0.85
CONSOLIDATION_SIMILARITY_FLAG = 0.70
CONSOLIDATION_INTERVAL_DAYS = 7
CONSOLIDATION_RESONANCE_THRESHOLD = 75.0
CONSOLIDATION_CONFIDENCE_THRESHOLD = 0.7
CONSOLIDATION_LOOKBACK_DAYS = 7
CONSOLIDATION_MAX_FILES_PER_PASS = 5

# ── Eval Harness ───────────────────────────────────────────────────
EVAL_LOG_DIR = PROJECT_ROOT / "logs" / "eval"
EVAL_LOG = EVAL_LOG_DIR / "results.jsonl"
EVAL_SUMMARY_LOG = EVAL_LOG_DIR / "summary.jsonl"
EVAL_JUDGE_MODEL = "qwen2.5:7b"  # 7B judges 14B — cross-model required
EVAL_SAMPLE_SIZE = 10  # for session-sampling mode
EVAL_PASS_THRESHOLD = 0.70
EVAL_MARGINAL_THRESHOLD = 0.50

# ── Adversarial Agency ─────────────────────────────────────────────
ADVERSARIAL_LOG_DIR = PROJECT_ROOT / "logs" / "adversarial"
ADVERSARIAL_PROBES_LOG = ADVERSARIAL_LOG_DIR / "probes.jsonl"
ADVERSARIAL_GENERATOR_MODEL = "qwen2.5:7b"  # Local 7B for probe generation
ADVERSARIAL_FAILURE_THRESHOLD = 0.5  # Sensitivity for regression flagging

# ── Gauntlet ──────────────────────────────────────────────────────
GAUNTLET_LOG_DIR = PROJECT_ROOT / "logs" / "gauntlet"
GAUNTLET_HISTORY_LOG = GAUNTLET_LOG_DIR / "history.jsonl"

# ── Daemon ───────────────────────────────────────────────────────────
DAEMON_HEARTBEAT_INTERVAL_SEC = 30
DAEMON_PID_FILE = PROJECT_ROOT / "logs" / "daemon.pid"
DAEMON_STOP_FILE = PROJECT_ROOT / "logs" / "daemon.stop"
DAEMON_LOG_FILE = PROJECT_ROOT / "logs" / "daemon.log"
DAEMON_VAULT_WATCH_DIRS = [VAULT_DIR / "knowledge", VAULT_DIR / "patterns", VAULT_DIR / "identity"]
DAEMON_SESSION_STALE_MINUTES = 30
DAEMON_SESSION_CHECK_INTERVAL_SEC = 300  # 5 min
DAEMON_BUDGET_ALERT_THRESHOLD = 0.80
DAEMON_BUDGET_CRITICAL_THRESHOLD = 0.95
DAEMON_BUDGET_CHECK_INTERVAL_SEC = 300  # 5 min
DAEMON_PREWARM_DATA_FILE = PROJECT_ROOT / "logs" / "activity_schedule.json"
DAEMON_PREWARM_MIN_SAMPLES = 7
DAEMON_PREWARM_LEAD_MINUTES = 5
DAEMON_LOG_ROTATION_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
DAEMON_LOG_ROTATION_INTERVAL_SEC = 3600  # 1 hour
DAEMON_LOG_ROTATION_KEEP_LINES = 2000

# ── API ─────────────────────────────────────────────────────────────
API_VERSION = "0.0.9"

# ── Browser / Research ───────────────────────────────────────────────
SEARXNG_URL = "http://127.0.0.1:8888"
RESEARCH_SUMMARIZER_MODEL = "qwen2.5:7b"

# ── Calibration ──────────────────────────────────────────────────────
SYNC_MANIFEST_PATH = Path("D:/COMMAND/SYNC_MANIFEST.md")
COMMAND_DIR = Path("D:/COMMAND")

# ── Context Engine ───────────────────────────────────────────────────
CONTEXT_ENGINE_HOT_WINDOW = 3           # Full tool outputs preserved
CONTEXT_ENGINE_WARM_CEILING = 10        # Warm tier: calls 4-10
CONTEXT_ENGINE_TOKEN_MULTIPLIER = 1.3   # Word-to-token approximation

# ── Tool Result Compression ───────────────────────────────────────────
COMPRESSOR_THRESHOLD_TOKENS = 1024      # Stage B triggers above this
COMPRESSOR_MAX_OUTPUT_TOKENS = 256      # LLM compression output cap
COMPRESSOR_MODEL = "qwen2.5:7b"         # Dedicated compression model (SYNTH ruling)
COMPRESSOR_ARRAY_PREVIEW_COUNT = 3      # Items shown before truncation

# ── Token Budget Tracker ─────────────────────────────────────────────
BUDGET_TIERS: dict[str, dict] = {
    "file_management":     {"max_input": 2000, "max_output": 1000, "max_tool_calls": 3,  "max_retries": 1},
    "vault_query":         {"max_input": 4000, "max_output": 2000, "max_tool_calls": 5,  "max_retries": 2},
    "research_web":        {"max_input": 8000, "max_output": 4000, "max_tool_calls": 10, "max_retries": 3},
    "browser_automation":  {"max_input": 6000, "max_output": 3000, "max_tool_calls": 8,  "max_retries": 2},
}
BUDGET_STATUS_THRESHOLDS = {"MEDIUM": 0.50, "LOW": 0.75, "CRITICAL": 0.90}

# ── Agency Logging ────────────────────────────────────────────────────
AGENCY_LOG_DIR = PROJECT_ROOT / "logs" / "agency"

# ── Autonomy Matrix ─────────────────────────────────────────────────
AUTONOMY_MATRIX_PATH = PROJECT_ROOT / "autonomy_matrix.json"
APPROVAL_PROPOSALS_LOG = AGENCY_LOG_DIR / "proposals.jsonl"

# ── File Management Agent ────────────────────────────────────────────
FILE_OPS_LOG = AGENCY_LOG_DIR / "file_ops.jsonl"


def _load_file_agent_allowed_paths() -> dict[str, str]:
    """FileAgent path scope from owner_identity.toml [paths.file_agent].

    Returns an empty dict when the config is missing — that disables the
    FileAgent entirely (every path resolves outside the empty scope).
    """
    from core.interface.owner_identity import load_owner_identity
    return dict(load_owner_identity().file_agent_paths)


FILE_AGENT_ALLOWED_PATHS: dict[str, str] = _load_file_agent_allowed_paths()

# ── Agent Framework ──────────────────────────────────────────────────
FRAMEWORK_AUDIT_LOG = AGENCY_LOG_DIR / "tool_audit.jsonl"
FRAMEWORK_DEFAULT_RATE_LIMIT = 60  # calls/min per tool, overridden per-tool
FRAMEWORK_MCP_PORT = 8421

# ── Multi-Provider Inference (T-037) ────────────────────────────────
PROVIDER_DEFAULT = "local"                   # default provider name
PROVIDER_CLOUD_DEFAULT = "claude"            # default cloud provider
PROVIDER_ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
PROVIDER_ANTHROPIC_MAX_TOKENS = 4096
PROVIDER_OLLAMA_BASE_URL = "http://localhost:11434"
