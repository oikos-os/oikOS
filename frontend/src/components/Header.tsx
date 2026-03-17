import type { SystemState } from "../types";

const FSM_COLORS: Record<string, string> = {
  active: "bg-green-500",
  idle: "bg-amber-500",
  asleep: "bg-blue-500",
};

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

interface Props {
  state: SystemState | null;
  wsConnected: boolean;
  activeModel?: string | null;
  onThemeToggle?: () => void;
  theme?: string;
}

export default function Header({ state, wsConnected, activeModel, onThemeToggle, theme }: Props) {
  const fsmState = state?.fsm_state ?? "---";
  const dotColor = FSM_COLORS[fsmState] ?? "bg-neutral-600";

  return (
    <header className="flex items-center justify-end px-4 py-1.5 border-b border-[var(--border-subtle)] text-sm">
      <div className="flex items-center gap-5">
        {activeModel && (
          <span className="text-amber-400/80 text-xs font-mono">{activeModel}</span>
        )}
        <span className="text-neutral-500 text-xs">v{state?.version ?? "---"}</span>

        <div className="flex items-center gap-2">
          <span className={`inline-block w-2 h-2 rounded-full ${dotColor}`} />
          <span className="uppercase tracking-wider text-white text-xs">{fsmState}</span>
        </div>

        {state && (
          <span className="text-neutral-500 text-xs">UP {formatUptime(state.uptime)}</span>
        )}

        <span
          className={`w-2 h-2 rounded-full ${wsConnected ? "bg-green-500 animate-pulse" : "bg-red-600"}`}
          title={wsConnected ? "WebSocket connected" : "WebSocket disconnected"}
        />

        {onThemeToggle && (
          <button
            onClick={onThemeToggle}
            className="text-neutral-500 hover:text-neutral-300 text-xs px-1"
            title="Toggle theme"
            data-testid="theme-toggle"
          >
            {theme === "light" ? "DARK" : "LIGHT"}
          </button>
        )}
      </div>
    </header>
  );
}
