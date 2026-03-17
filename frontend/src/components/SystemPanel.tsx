import type { HealthStatus, HeartbeatPayload } from "../types";

interface Props {
  health: HealthStatus | null;
  heartbeat: HeartbeatPayload | null;
}

function Bar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div className="h-2 bg-neutral-700/50 rounded-full w-full">
      <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function SystemPanel({ health, heartbeat }: Props) {
  const daemon = heartbeat?.daemon ?? health?.daemon;
  const vramUsed = daemon?.vram_used_mb ?? 0;
  const vramTotal = daemon?.vram_total_mb ?? 0;
  const ollamaOk = daemon?.ollama_reachable ?? health?.ollama_embed ?? false;
  const daemonRunning = health?.running ?? daemon?.running ?? false;

  return (
    <section className="bg-[#242424] rounded-xl p-4">
      <h2 className="text-sm tracking-widest text-neutral-400 mb-3">SYSTEM</h2>

      <div className="space-y-3">
        <div>
          <div className="flex justify-between text-neutral-300 mb-1">
            <span>VRAM</span>
            <span className="text-white">{vramUsed} / {vramTotal} MB</span>
          </div>
          <Bar value={vramUsed} max={vramTotal} color="bg-amber-500" />
        </div>

        <div className="flex justify-between text-neutral-300">
          <span>Ollama</span>
          <span className={ollamaOk ? "text-green-500" : "text-red-500"}>
            {ollamaOk ? "ONLINE" : "OFFLINE"}
          </span>
        </div>

        <div className="flex justify-between text-neutral-300">
          <span>Daemon</span>
          <span className={daemonRunning ? "text-green-500" : "text-neutral-600"}>
            {daemonRunning ? "RUNNING" : "STOPPED"}
          </span>
        </div>

        {daemon?.inference_active && (
          <div className="text-amber-400 text-xs animate-pulse">
            INFERENCE ACTIVE
          </div>
        )}
      </div>
    </section>
  );
}
