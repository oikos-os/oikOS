import { useState } from "react";

interface Props {
  name: string;
  setName: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
  onNext: () => void;
}

export default function StepIdentity({ name, setName, description, setDescription, onNext }: Props) {
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleNext() {
    setError("");
    setSaving(true);
    try {
      const res = await fetch("/api/onboarding/identity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), description: description.trim() }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: "Request failed" }));
        setError(data.detail || "Failed to save identity");
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
        <h2 className="text-xl text-white mb-1">Name your oikOS</h2>
        <p className="text-neutral-400 text-sm">Give your system an identity. This is stored locally in your vault.</p>
      </div>

      <div className="space-y-4">
        <div>
          <label className="block text-sm text-neutral-400 mb-1">Name</label>
          <input
            type="text"
            maxLength={64}
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="e.g. Atlas, Friday, Jarvis"
            className="w-full bg-[#0a0a0a] border border-neutral-800 px-3 py-2 text-white placeholder:text-neutral-600 focus:border-amber-400 focus:outline-none"
          />
          <span className="text-xs text-neutral-600 mt-1 block">{name.length}/64</span>
        </div>

        <div>
          <label className="block text-sm text-neutral-400 mb-1">Description (optional)</label>
          <textarea
            value={description}
            onChange={e => setDescription(e.target.value)}
            rows={3}
            placeholder="What is this system for?"
            className="w-full bg-[#0a0a0a] border border-neutral-800 px-3 py-2 text-white placeholder:text-neutral-600 focus:border-amber-400 focus:outline-none resize-none"
          />
        </div>
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      <div className="flex justify-end">
        <button
          onClick={handleNext}
          disabled={!name.trim() || saving}
          className="px-6 py-2 bg-amber-400 text-black font-medium hover:bg-amber-300 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {saving ? "Saving..." : "Next"}
        </button>
      </div>
    </div>
  );
}
