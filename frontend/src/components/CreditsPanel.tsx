import type { CreditBalance, SystemConfig } from "../types";

interface Props {
  credits: CreditBalance | null;
  config: SystemConfig | null;
}

function CreditBar({ used, cap }: { used: number; cap: number }) {
  const pct = cap > 0 ? Math.min((used / cap) * 100, 100) : 0;
  let color = "bg-green-500";
  if (pct > 80) color = "bg-red-500";
  else if (pct > 50) color = "bg-amber-500";

  return (
    <div className="h-2 bg-neutral-700/50 rounded-full w-full">
      <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function CreditsPanel({ credits, config }: Props) {
  const used = credits?.used_this_month ?? 0;
  const cap = credits?.monthly_cap ?? 0;
  const remaining = credits?.remaining ?? 0;
  const posture = config?.cloud_posture ?? "---";

  return (
    <section className="bg-[#242424] rounded-xl p-4">
      <h2 className="text-sm tracking-widest text-neutral-400 mb-3">CREDITS</h2>

      <div className="space-y-3">
        <div>
          <div className="flex justify-between text-neutral-300 mb-1">
            <span>Usage</span>
            <span className="text-white">{used.toLocaleString()} / {cap.toLocaleString()}</span>
          </div>
          <CreditBar used={used} cap={cap} />
        </div>

        <div className="flex justify-between text-neutral-300">
          <span>Remaining</span>
          <span className="text-white">{remaining.toLocaleString()}</span>
        </div>

        <div className="flex justify-between text-neutral-300">
          <span>Posture</span>
          <span className="uppercase tracking-wider text-white">{posture}</span>
        </div>
      </div>
    </section>
  );
}
