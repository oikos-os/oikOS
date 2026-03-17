"""Paths, constants, and budgets for OIKOS_OMEGA."""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
VAULT_DIR = PROJECT_ROOT / "vault"
LANCEDB_DIR = PROJECT_ROOT / "memory" / "lancedb"
LOGS_DIR = PROJECT_ROOT / "logs" / "sessions"

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

# ── Compiler Hierarchy (Phase 7a, Module 1) ──────────────────────────
# Identity tier gets a fixed non-competitive allocation loaded before all others.
# SLICE_ALLOCATIONS values are percentages of the REMAINING budget after identity.
IDENTITY_BUDGET_PCT = 0.20      # 20% of total budget — non-negotiable
IDENTITY_TELOS_LIMIT = 3        # max TELOS anchor chunks loaded in identity slice
IDENTITY_FALLBACK_STRING = (
    "You are oikOS. The Lieutenant. "
    "Serve the Architect. Maintain the Vantablack Standard."
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
INFERENCE_TEMPERATURE = 0.7
INFERENCE_TOP_P = 0.9
INFERENCE_MAX_TOKENS = 2048
INFERENCE_TIMEOUT_SECONDS = 60

# ── PII ───────────────────────────────────────────────────────────────
PII_CONFIDENCE_THRESHOLD = 0.3  # Aggressive: over-scrub > under-scrub (SYNTH review, Architect approved)
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
ROUTING_COSINE_SENSITIVITY_THRESHOLD = 0.75  # calibrate via scripts/calibrate_sensitivity.py
ROUTING_COSINE_ENTITY_DELTA = 0.15  # drop threshold by this when sovereign entities detected

# ── Credits ───────────────────────────────────────────────────────────
CREDITS_FILE = PROJECT_ROOT / "core" / "credits.json"
CREDITS_MONTHLY_CAP = 1000000
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
SCANNER_RESONANCE_THRESHOLD = 60.0
SCANNER_BLIP_EXPIRY_DAYS = 30
SCANNER_BLIP_LOG = PROJECT_ROOT / "logs" / "scanner" / "blips.jsonl"

# ── Cloud Routing Posture ────────────────────────────────────────────
# Controls how readily the system reaches for cloud.
#   "conservative" — skip_local requires 3+ signals (minimize cloud spend)
#   "balanced"     — skip_local requires 2+ signals (default)
#   "aggressive"   — skip_local on any single signal (maximize quality)
CLOUD_ROUTING_POSTURE = "balanced"

# ── Assertions (Module 3) ────────────────────────────────────────────
ASSERTION_LOG_DIR = PROJECT_ROOT / "logs" / "assertions"
ASSERTION_CLASSIFIER_MODEL = "qwen2.5:7b"
ASSERTION_MAX_TOKENS = 80

# ── Complexity Pre-Scorer ───────────────────────────────────────────
COMPLEXITY_LENGTH_THRESHOLD = 50  # tokens — queries above this get length penalty
COMPLEXITY_LENGTH_PENALTY = 10.0
COMPLEXITY_DOMAIN_PENALTY = 15.0  # abstract/strategic keywords detected
COMPLEXITY_MULTI_DOMAIN_PENALTY = 15.0  # query touches 2+ vault domains
COMPLEXITY_CREATIVE_PENALTY = 15.0  # narrative/aesthetic/musical keywords

# skip_local threshold — derived from posture
_POSTURE_THRESHOLDS = {"conservative": 35.0, "balanced": 20.0, "aggressive": 5.0}
COMPLEXITY_SKIP_LOCAL_THRESHOLD = _POSTURE_THRESHOLDS.get(CLOUD_ROUTING_POSTURE, 20.0)

# ── Consolidation (Phase 7b, Module 5) ───────────────────────────────
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
ADVERSARIAL_GENERATOR_MODEL = "gemini-2.5-pro"  # Cloud for novelty
ADVERSARIAL_FAILURE_THRESHOLD = 0.5  # Sensitivity for regression flagging

# ── Gauntlet ──────────────────────────────────────────────────────
GAUNTLET_LOG_DIR = PROJECT_ROOT / "logs" / "gauntlet"
GAUNTLET_HISTORY_LOG = GAUNTLET_LOG_DIR / "history.jsonl"

# ── Daemon (Phase 7b) ────────────────────────────────────────────────
DAEMON_HEARTBEAT_INTERVAL_SEC = 30
DAEMON_IDLE_TIMEOUT_MINUTES = 15
DAEMON_VRAM_YIELD_THRESHOLD_MB = 11264
DAEMON_HEALTH_CHECK_INTERVAL_SEC = 60
DAEMON_HEALTH_FAILURES_RESTART = 3
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
API_DEFAULT_PORT = 8420
API_VERSION = "1.0.0-rc1"

# ── Calibration ──────────────────────────────────────────────────────
SYNC_MANIFEST_PATH = Path("D:/COMMAND/SYNC_MANIFEST.md")
COMMAND_DIR = Path("D:/COMMAND")

# ── Context Engine (Phase 7d Module 1) ────────────────────────────────
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

# ── Autonomy Matrix (Phase 7d Module 2) ─────────────────────────────
AUTONOMY_MATRIX_PATH = PROJECT_ROOT / "autonomy_matrix.json"
APPROVAL_TIMEOUT_SECONDS = 3600  # 1 hour — proposals expire, treated as rejection
APPROVAL_PROPOSALS_LOG = AGENCY_LOG_DIR / "proposals.jsonl"

# ── File Management Agent (Phase 7d Module 3) ───────────────────────
FILE_OPS_LOG = AGENCY_LOG_DIR / "file_ops.jsonl"
FILE_AGENT_ALLOWED_PATHS: dict[str, str] = {
    "D:/SIGMA/Vault/SIGMA_VAULT": "READ",
    "D:/COMMAND": "READ",
    "D:/COMMAND/staging": "READ_WRITE",
    "D:/COMMAND/messages": "READ_WRITE",
    "D:/Development/OIKOS_OMEGA/docs": "READ",
    "D:/Development/ORACLE": "READ",
}

# ── Agent Framework (Phase 7e Module 0) ──────────────────────────────
FRAMEWORK_AUDIT_LOG = AGENCY_LOG_DIR / "tool_audit.jsonl"
FRAMEWORK_DEFAULT_RATE_LIMIT = 60  # calls/min per tool, overridden per-tool
FRAMEWORK_MCP_PORT = 8421

# ── Multi-Provider Inference (T-037) ────────────────────────────────
PROVIDER_DEFAULT = "local"                   # default provider name
PROVIDER_CLOUD_DEFAULT = "claude"            # default cloud provider
PROVIDER_ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
PROVIDER_ANTHROPIC_MAX_TOKENS = 4096
PROVIDER_OLLAMA_BASE_URL = "http://localhost:11434"
