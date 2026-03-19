import type { EventRecord } from "../types";

interface Props {
  events: EventRecord[] | null;
}

const CATEGORY_COLORS: Record<string, string> = {
  fsm: "text-neutral-400",
  inference: "text-stone-400",
  agent: "text-zinc-400",
  cloud: "text-slate-400",
  error: "text-red-400",
};

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts;
  }
}

export default function ActivityFeed({ events }: Props) {
  const items = events ?? [];

  return (
    <section className="bg-[#242424] rounded-xl p-4 flex flex-col min-h-0">
      <h2 className="text-sm tracking-widest text-neutral-400 mb-3">ACTIVITY</h2>

      <div className="overflow-y-auto flex-1 space-y-1 text-sm font-mono" data-testid="activity-feed">
        {items.length === 0 && (
          <p className="text-neutral-600">No events.</p>
        )}
        {items.map((ev, i) => (
          <div key={`${ev.timestamp}-${i}`} className="flex gap-2">
            <span className="text-neutral-500 shrink-0">{formatTime(ev.timestamp)}</span>
            <span className={`shrink-0 ${CATEGORY_COLORS[ev.category] ?? "text-neutral-400"}`}>
              [{ev.category}]
            </span>
            <span className="text-white truncate">{ev.type}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
