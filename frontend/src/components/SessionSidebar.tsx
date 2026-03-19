import { useEffect, useState } from "react";
import type { SessionSummary } from "../types";

interface Props {
  onSelect: (sessionId: string) => void;
  onNewSession: () => void;
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString([], { month: "short", day: "numeric" }) +
      " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

export default function SessionSidebar({ onSelect, onNewSession }: Props) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);

  useEffect(() => {
    fetch("/api/chat/history?limit=20")
      .then((r) => r.ok ? r.json() : [])
      .then(setSessions)
      .catch(() => {});
  }, []);

  return (
    <aside className="w-56 bg-[#212121] rounded-2xl m-2 flex flex-col overflow-hidden" data-testid="session-sidebar">
      <div className="p-3">
        <button
          onClick={onNewSession}
          className="w-full text-sm font-semibold tracking-wider bg-white text-black rounded-lg py-2 hover:bg-neutral-200 transition-colors"
        >
          NEW SESSION
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {sessions.map((s) => (
          <button
            key={s.session_id}
            onClick={() => onSelect(s.session_id)}
            className="w-full text-left px-3 py-2.5 hover:bg-neutral-700/30 text-sm transition-colors rounded-lg mx-auto"
          >
            <div className="text-white truncate">
              {s.first_query || s.session_id.slice(0, 8)}
            </div>
            <div className="text-neutral-500 text-xs">
              {formatDate(s.started_at)} &middot; {s.interaction_count} msgs
            </div>
          </button>
        ))}
        {sessions.length === 0 && (
          <p className="text-neutral-500 text-sm p-3">No sessions.</p>
        )}
      </div>
    </aside>
  );
}
