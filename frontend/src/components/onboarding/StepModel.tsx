import { useEffect, useState } from "react";
import type { DetectedBackend } from "../../types";
import BackendCard from "./BackendCard";

interface Props {
  backends: DetectedBackend[];
  setBackends: (b: DetectedBackend[]) => void;
  selectedModel: { provider: string; model: string } | null;
  setSelectedModel: (m: { provider: string; model: string } | null) => void;
  onNext: () => void;
  onBack: () => void;
}

export default function StepModel({ backends, setBackends, selectedModel, setSelectedModel, onNext, onBack }: Props) {
  const [scanning, setScanning] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch("/api/onboarding/detect-backends")
      .then(r => r.ok ? r.json() : [])
      .then((data: DetectedBackend[]) => setBackends(data))
      .catch(() => setBackends([]))
      .finally(() => setScanning(false));
  }, [setBackends]);

  const selected = selectedModel ? `${selectedModel.provider}::${selectedModel.model}` : null;

  async function handleNext() {
    if (!selectedModel) return;
    setError("");
    setSaving(true);
    try {
      const res = await fetch("/api/onboarding/model", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(selectedModel),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: "Request failed" }));
        setError(data.detail || "Failed to save model selection");
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
        <h2 className="text-xl text-white mb-1">Select a local model</h2>
        <p className="text-neutral-400 text-sm">oikOS scans for running inference backends on your machine.</p>
      </div>

      {scanning ? (
        <div className="flex items-center gap-3 py-8 justify-center">
          <div className="w-4 h-4 border-2 border-amber-400 border-t-transparent animate-spin" />
          <span className="text-neutral-400">Scanning local backends...</span>
        </div>
      ) : backends.length === 0 ? (
        <div className="bg-[#1a1a1a] border border-neutral-800 p-6 text-center space-y-3">
          <p className="text-neutral-400">No local backends found</p>
          <p className="text-neutral-600 text-sm">
            Install{" "}
            <a href="https://ollama.com" target="_blank" rel="noopener noreferrer" className="text-amber-400 hover:underline">
              Ollama
            </a>
            {" "}to run models locally.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {backends.map(b => (
            <BackendCard
              key={b.backend}
              backend={b}
              selectedModel={selected}
              onSelect={(provider, model) => setSelectedModel({ provider, model })}
            />
          ))}
        </div>
      )}

      {error && <p className="text-red-400 text-sm">{error}</p>}

      <div className="flex justify-between">
        <button onClick={onBack} className="px-4 py-2 border border-neutral-800 text-neutral-400 hover:text-white">
          Back
        </button>
        <div className="flex gap-3">
          <button onClick={onNext} className="px-4 py-2 text-neutral-400 hover:text-white">
            Skip
          </button>
          <button
            onClick={handleNext}
            disabled={!selectedModel || saving}
            className="px-6 py-2 bg-amber-400 text-black font-medium hover:bg-amber-300 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {saving ? "Saving..." : "Next"}
          </button>
        </div>
      </div>
    </div>
  );
}
