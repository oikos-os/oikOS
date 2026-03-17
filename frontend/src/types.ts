export interface SystemState {
  fsm_state: "active" | "idle" | "asleep";
  model: string;
  version: string;
  uptime: number;
  last_transition: string | null;
}

export interface DaemonStatus {
  running: boolean;
  vram_used_mb?: number;
  vram_total_mb?: number;
  ollama_reachable?: boolean;
  inference_active?: boolean;
}

export interface HealthStatus {
  running: boolean;
  daemon: DaemonStatus;
  ollama_embed: boolean;
}

export interface CreditBalance {
  monthly_cap: number;
  used_this_month: number;
  remaining: number;
  last_reset: string;
}

export interface SystemConfig {
  version: string;
  inference_model: string;
  cloud_model: string;
  token_budget: number;
  monthly_cap: number;
  confidence_threshold: number;
  cloud_posture: string;
}

export interface VaultStats {
  total_rows: number;
  tier_breakdown?: Record<string, number>;
}

export interface AgentEvalLatest {
  timestamp?: string;
  total?: number;
  passed?: number;
  avg_score?: number;
  [key: string]: unknown;
}

export interface AgentGauntletLatest {
  timestamp?: string;
  total?: number;
  passed?: number;
  soft_fails?: number;
  hard_fails?: number;
  regressions?: number;
  [key: string]: unknown;
}

export interface EventRecord {
  timestamp: string;
  category: string;
  type: string;
  data: Record<string, unknown>;
}

export interface HeartbeatPayload {
  fsm_state: "active" | "idle" | "asleep";
  daemon: DaemonStatus;
}

export interface PipelineTrace {
  pii: boolean;
  adversarial: boolean;
  cosine_gate: boolean;
  contradiction: boolean;
  coherence: boolean;
  output_filter: boolean;
}

export interface ChatDonePayload {
  done: true;
  route: string | null;
  model: string | null;
  confidence: number | null;
  pii_scrubbed: boolean;
  pipeline: PipelineTrace;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  confidence?: number | null;
  route?: string | null;
  model?: string | null;
  pipeline?: PipelineTrace;
  pii_scrubbed?: boolean;
}

export interface SessionSummary {
  session_id: string;
  started_at: string;
  closed_at?: string;
  interaction_count: number;
  avg_confidence?: number | null;
  routes?: Record<string, number>;
  first_query?: string;
}

export interface SessionEntry {
  type: "query" | "response";
  timestamp: string;
  session_id: string;
  query_hash: string;
  query?: string;
  route?: string;
  model_used?: string;
  confidence?: number;
  response_text?: string;
  response_preview?: string;
}
