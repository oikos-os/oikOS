import { useCallback, useEffect, useRef, useState } from "react";
import { IconChevronDown } from "./icons";
import type { RoomConfig } from "../types";

interface ModelInfo {
  name: string;
  size?: number;
  type?: string;
  provider?: string;
}

interface Props {
  activeRoom: RoomConfig | null;
  onRoomUpdated?: (room: RoomConfig) => void;
  lastUsedModel?: string | null;
}

export default function ModelSelector({ activeRoom, onRoomUpdated, lastUsedModel }: Props) {
  const [open, setOpen] = useState(false);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const currentModel = activeRoom?.model?.model;
  const currentProvider = activeRoom?.model?.provider;
  const isAuto = !currentModel && !currentProvider;

  useEffect(() => {
    fetch("/api/models")
      .then((r) => (r.ok ? r.json() : { local: [], cloud: [] }))
      .then((data) => {
        const all: ModelInfo[] = [...(data.local || []), ...(data.cloud || [])];
        setModels(all);
      })
      .catch(() => {});
  }, []);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const selectModel = useCallback(
    async (value: string) => {
      if (!activeRoom) return;
      setOpen(false);
      const resp = await fetch(`/api/rooms/${activeRoom.id}/model`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: value }),
      });
      if (resp.ok && onRoomUpdated) {
        onRoomUpdated(await resp.json());
      }
    },
    [activeRoom, onRoomUpdated],
  );

  // Display label
  let label = "Auto";
  if (isAuto && lastUsedModel) {
    label = `Auto \u2192 ${lastUsedModel}`;
  } else if (currentModel) {
    label = currentModel;
  } else if (currentProvider) {
    label = currentProvider + ":";
  }

  return (
    <div ref={dropdownRef} className="relative" data-testid="model-selector">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 px-2 py-0.5 text-xs text-amber-400/80 hover:text-amber-300 transition-colors font-mono"
        data-testid="model-selector-button"
      >
        <span className="max-w-[180px] truncate">{label}</span>
        <IconChevronDown className="w-3 h-3 flex-shrink-0" />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 bg-[#0D0D0D] border border-neutral-700/50 py-1 min-w-[200px] z-50">
          {/* Auto option */}
          <button
            onClick={() => selectModel("auto")}
            className={`block w-full text-left px-3 py-1.5 text-sm font-mono ${isAuto ? "text-amber-400 bg-[#1A1205]" : "text-neutral-400 hover:text-white hover:bg-[#1A1205]"}`}
            data-testid="model-option-auto"
          >
            Auto
            <span className="text-neutral-600 text-xs ml-2">local \u2192 cloud</span>
          </button>

          {/* Separator */}
          <div className="border-t border-neutral-700/30 my-1" />

          {/* Available models */}
          {models.map((m) => {
            const isActive = currentModel === m.name;
            return (
              <button
                key={m.name}
                onClick={() => selectModel(m.type === "cloud" && m.provider ? `${m.provider}:${m.name}` : m.name)}
                className={`block w-full text-left px-3 py-1.5 text-sm font-mono ${isActive ? "text-amber-400 bg-[#1A1205]" : "text-neutral-400 hover:text-white hover:bg-[#1A1205]"}`}
              >
                {m.name}
                {m.type === "cloud" && (
                  <span className="text-neutral-600 text-xs ml-2">cloud</span>
                )}
              </button>
            );
          })}
          {models.length === 0 && (
            <span className="block px-3 py-1.5 text-sm text-neutral-500 font-mono">No models found</span>
          )}
        </div>
      )}
    </div>
  );
}
