import { useState } from "react";

const TEMPLATES = [
  { id: "researcher", name: "Researcher", desc: "Deep-dive analysis, paper review, knowledge synthesis" },
  { id: "code", name: "Code", desc: "Software development, debugging, architecture" },
  { id: "writing", name: "Writing", desc: "Long-form content, editing, brainstorming" },
  { id: "finance", name: "Finance", desc: "Market analysis, budgets, financial tracking" },
  { id: "health", name: "Health", desc: "Fitness tracking, nutrition, wellness logs" },
];

interface Props {
  selectedRoom: string | null;
  setSelectedRoom: (v: string | null) => void;
  onNext: () => void;
  onBack: () => void;
}

export default function StepRooms({ selectedRoom, setSelectedRoom, onNext, onBack }: Props) {
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleNext() {
    if (!selectedRoom) { onNext(); return; }
    setError("");
    setSaving(true);
    try {
      const res = await fetch("/api/onboarding/rooms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ template: selectedRoom }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: "Request failed" }));
        setError(data.detail || "Failed to create room");
        return;
      }
      onNext();
    } catch {
      setError("Network error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl text-white mb-1">Create a Room (optional)</h2>
        <p className="text-neutral-400 text-sm">
          Rooms are isolated workspaces with their own vault scope, model config, and personality.
          You can always create more later.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {TEMPLATES.map(t => (
          <button
            key={t.id}
            onClick={() => setSelectedRoom(selectedRoom === t.id ? null : t.id)}
            className={`text-left p-4 border transition-colors ${
              selectedRoom === t.id
                ? "border-amber-400 bg-amber-400/5"
                : "border-neutral-800 bg-[#1a1a1a] hover:border-neutral-700"
            }`}
          >
            <span className="text-white font-medium block mb-1">{t.name}</span>
            <span className="text-neutral-400 text-sm">{t.desc}</span>
          </button>
        ))}
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      <div className="flex justify-between">
        <button onClick={onBack} className="px-4 py-2 border border-neutral-800 text-neutral-400 hover:text-white">
          Back
        </button>
        <div className="flex gap-3">
          <button onClick={() => { setSelectedRoom(null); onNext(); }} className="px-4 py-2 text-neutral-400 hover:text-white">
            Skip
          </button>
          <button
            onClick={handleNext}
            disabled={saving}
            className="px-6 py-2 bg-amber-400 text-black font-medium hover:bg-amber-300 disabled:opacity-40"
          >
            {saving ? "Creating..." : "Next"}
          </button>
        </div>
      </div>
    </div>
  );
}
