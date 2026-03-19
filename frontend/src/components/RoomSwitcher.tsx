import { useState, useEffect, useRef } from "react";
import type { RoomConfig } from "../types";

interface Props {
  activeRoom: RoomConfig | null;
  onSwitch: (roomId: string) => void;
}

export default function RoomSwitcher({ activeRoom, onSwitch }: Props) {
  const [open, setOpen] = useState(false);
  const [rooms, setRooms] = useState<RoomConfig[]>([]);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      fetch("/api/rooms").then(r => r.ok ? r.json() : []).then(setRooms).catch(() => {});
    }
  }, [open]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  if (!activeRoom) return null;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-2 py-0.5 text-xs text-amber-400/90 hover:text-amber-300 transition-colors"
        title={`Room: ${activeRoom.name}`}
      >
        <span className="w-1.5 h-1.5 bg-amber-400 rounded-full" />
        <span className="font-mono tracking-wide">{activeRoom.name.toUpperCase()}</span>
        <svg viewBox="0 0 10 6" width="8" height="5" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M1 1l4 4 4-4" />
        </svg>
      </button>
      {open && rooms.length > 0 && (
        <div className="absolute right-0 top-full mt-1 w-48 bg-[#1a1a1a] border border-neutral-800 shadow-lg z-50">
          {rooms.map(r => (
            <button
              key={r.id}
              onClick={() => { onSwitch(r.id); setOpen(false); }}
              className={`w-full text-left px-3 py-1.5 text-xs transition-colors ${
                r.id === activeRoom.id
                  ? "text-amber-400 bg-[#2a2a2a]"
                  : "text-neutral-400 hover:text-white hover:bg-[#222]"
              }`}
            >
              {r.name}
              {r.description && <span className="block text-[10px] text-neutral-600 truncate">{r.description}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
