import { useState, useEffect, useCallback } from "react";
import type { RoomConfig } from "../types";

const TEMPLATES = ["researcher", "code", "writing", "health", "finance"];

export default function RoomManager() {
  const [rooms, setRooms] = useState<RoomConfig[]>([]);
  const [active, setActive] = useState<string>("home");
  const [creating, setCreating] = useState(false);
  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newTemplate, setNewTemplate] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(() => {
    fetch("/api/rooms").then(r => r.ok ? r.json() : []).then(setRooms).catch(() => {});
    fetch("/api/rooms/active").then(r => r.ok ? r.json() : null).then(r => r && setActive(r.id)).catch(() => {});
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const handleCreate = async () => {
    setError("");
    const body: Record<string, unknown> = { id: newId, name: newName, description: newDesc };
    if (newTemplate) body.template = newTemplate;
    const resp = await fetch("/api/rooms", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!resp.ok) { setError((await resp.json()).detail || "Failed"); return; }
    setCreating(false); setNewId(""); setNewName(""); setNewDesc(""); setNewTemplate("");
    refresh();
  };

  const handleDelete = async (id: string) => {
    if (!confirm(`Delete room "${id}"?`)) return;
    await fetch(`/api/rooms/${id}`, { method: "DELETE" });
    refresh();
  };

  const handleSwitch = async (id: string) => {
    await fetch("/api/rooms/switch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ room_id: id }) });
    refresh();
  };

  return (
    <main className="flex-1 overflow-y-auto p-6 max-w-3xl mx-auto w-full">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-lg font-bold tracking-widest text-white uppercase">Rooms</h1>
        <button
          onClick={() => setCreating(!creating)}
          className="px-3 py-1 text-xs text-amber-400 border border-amber-400/30 hover:bg-amber-400/10 transition-colors"
        >
          {creating ? "CANCEL" : "+ NEW ROOM"}
        </button>
      </div>

      {creating && (
        <div className="mb-6 p-4 bg-[#1a1a1a] border border-neutral-800">
          <div className="grid grid-cols-2 gap-3 mb-3">
            <input value={newId} onChange={e => setNewId(e.target.value)} placeholder="room-id" className="bg-[#0a0a0a] border border-neutral-800 px-2 py-1 text-sm text-white placeholder-neutral-600" />
            <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="Display Name" className="bg-[#0a0a0a] border border-neutral-800 px-2 py-1 text-sm text-white placeholder-neutral-600" />
          </div>
          <input value={newDesc} onChange={e => setNewDesc(e.target.value)} placeholder="Description" className="w-full bg-[#0a0a0a] border border-neutral-800 px-2 py-1 text-sm text-white placeholder-neutral-600 mb-3" />
          <div className="flex items-center gap-3 mb-3">
            <span className="text-xs text-neutral-500">Template:</span>
            <select value={newTemplate} onChange={e => setNewTemplate(e.target.value)} className="bg-[#0a0a0a] border border-neutral-800 px-2 py-1 text-xs text-white">
              <option value="">None (blank)</option>
              {TEMPLATES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          {error && <p className="text-red-400 text-xs mb-2">{error}</p>}
          <button onClick={handleCreate} disabled={!newId || !newName} className="px-3 py-1 text-xs bg-amber-400/20 text-amber-400 hover:bg-amber-400/30 disabled:opacity-30 transition-colors">CREATE</button>
        </div>
      )}

      <div className="space-y-2">
        {rooms.map(r => (
          <div key={r.id} className={`flex items-center gap-4 p-3 border transition-colors ${r.id === active ? "border-amber-400/30 bg-[#1a1a0a]" : "border-neutral-800 bg-[#1a1a1a]"}`}>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-mono text-white">{r.name}</span>
                {r.id === active && <span className="text-[10px] text-amber-400 uppercase tracking-widest">Active</span>}
              </div>
              <p className="text-xs text-neutral-500 truncate">{r.description || "No description"}</p>
              <div className="flex gap-2 mt-1">
                <span className="text-[10px] text-neutral-600">scope: {r.vault_scope.mode}</span>
                <span className="text-[10px] text-neutral-600">tools: {r.toolsets ? r.toolsets.join(", ") : "all"}</span>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {r.id !== active && (
                <button onClick={() => handleSwitch(r.id)} className="px-2 py-0.5 text-[10px] text-amber-400 border border-amber-400/20 hover:bg-amber-400/10 transition-colors">SWITCH</button>
              )}
              {r.id !== "home" && (
                <button onClick={() => handleDelete(r.id)} className="px-2 py-0.5 text-[10px] text-red-400 border border-red-400/20 hover:bg-red-400/10 transition-colors">DELETE</button>
              )}
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
