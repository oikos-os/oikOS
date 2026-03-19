import { useEffect, useState } from "react";
import type { DetectedBackend } from "../../types";
import BackendCard from "./BackendCard";
import ProviderCard from "./ProviderCard";

type InferenceMode = null | "local" | "cloud" | "both";

const PROVIDERS = [
  { provider: "anthropic", label: "Anthropic (Claude)", note: "Requires API key from console.anthropic.com (separate from Claude Pro/Max subscription)" },
  { provider: "openai", label: "OpenAI (GPT)", note: "" },
  { provider: "gemini", label: "Google (Gemini)", note: "" },
];

interface Props {
  backends: DetectedBackend[];
  setBackends: (b: DetectedBackend[]) => void;
  selectedModel: { provider: string; model: string } | null;
  setSelectedModel: (m: { provider: string; model: string } | null) => void;
  configuredProviders: string[];
  setConfiguredProviders: (v: string[]) => void;
  onNext: () => void;
  onBack: () => void;
}

export default function StepInference({
  backends, setBackends, selectedModel, setSelectedModel,
  configuredProviders, setConfiguredProviders, onNext, onBack,
}: Props) {
  const [mode, setMode] = useState<InferenceMode>(null);
  const [scanning, setScanning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const showLocal = mode === "local" || mode === "both";
  const showCloud = mode === "cloud" || mode === "both";

  useEffect(() => {
    if (showLocal && backends.length === 0) {
      setScanning(true);
      fetch("/api/onboarding/detect-backends")
        .then(r => r.ok ? r.json() : [])
        .then((data: DetectedBackend[]) => setBackends(data))
        .catch(() => setBackends([]))
        .finally(() => setScanning(false));
    }
  }, [showLocal, backends.length, setBackends]);

  const selected = selectedModel ? `${selectedModel.provider}::${selectedModel.model}` : null;

  function handleProviderConnected(provider: string) {
    setConfiguredProviders([...new Set([...configuredProviders, provider])]);
  }

  async function handleNext() {
    setError("");
    if (showLocal && selectedModel) {
      setSaving(true);
      try {
        const res = await fetch("/api/onboarding/model", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(selectedModel),
        });
        if (!res.ok) {
          setError("Failed to save model selection");
          setSaving(false);
          return;
        }
      } catch {
        setError("Network error");
        setSaving(false);
        return;
      }
      setSaving(false);
    }
    onNext();
  }

  const canProceed = mode === "cloud"
    ? configuredProviders.length > 0
    : mode === "local"
      ? !!selectedModel
      : mode === "both"
        ? !!selectedModel || configuredProviders.length > 0
        : false;

  // Step 1: Choose mode
  if (mode === null) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-xl text-white mb-1">How do you want to run your AI?</h2>
          <p className="text-neutral-400 text-sm">You can always change this later in Settings.</p>
        </div>

        <div className="space-y-3">
          <button
            onClick={() => setMode("local")}
            className="w-full text-left bg-[#1a1a1a] border border-neutral-800 hover:border-amber-400/50 p-4 transition-colors"
          >
            <span className="text-white font-medium block">Local models</span>
            <span className="text-neutral-500 text-sm">Runs on your machine. Private, free, no internet needed.</span>
          </button>

          <button
            onClick={() => setMode("cloud")}
            className="w-full text-left bg-[#1a1a1a] border border-neutral-800 hover:border-amber-400/50 p-4 transition-colors"
          >
            <span className="text-white font-medium block">Cloud providers</span>
            <span className="text-neutral-500 text-sm">API key required. More powerful models for complex queries.</span>
          </button>

          <button
            onClick={() => setMode("both")}
            className="w-full text-left bg-[#1a1a1a] border border-neutral-800 hover:border-amber-400/50 p-4 transition-colors"
          >
            <span className="text-white font-medium block">Both</span>
            <span className="text-neutral-500 text-sm">Local for privacy, cloud for power. oikOS routes automatically.</span>
          </button>
        </div>

        <div className="flex justify-between">
          <button onClick={onBack} className="px-4 py-2 border border-neutral-800 text-neutral-400 hover:text-white">
            Back
          </button>
          <button onClick={onNext} className="px-4 py-2 text-neutral-400 hover:text-white">
            Skip
          </button>
        </div>
      </div>
    );
  }

  // Step 2: Configure based on mode
  return (
    <div className="space-y-6">
      <button
        onClick={() => setMode(null)}
        className="text-xs text-neutral-600 hover:text-amber-400 transition-colors"
      >
        &larr; Change selection
      </button>

      {showLocal && (
        <div className="space-y-4">
          <div>
            <h2 className="text-xl text-white mb-1">Local models</h2>
            <p className="text-neutral-400 text-sm">Scanning for running inference backends...</p>
          </div>

          {scanning ? (
            <div className="flex items-center gap-3 py-6 justify-center">
              <div className="w-4 h-4 border-2 border-amber-400 border-t-transparent animate-spin" />
              <span className="text-neutral-400">Scanning...</span>
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
        </div>
      )}

      {showLocal && showCloud && <hr className="border-neutral-800" />}

      {showCloud && (
        <div className="space-y-4">
          <div>
            <h2 className="text-xl text-white mb-1">Cloud providers</h2>
            <p className="text-neutral-400 text-sm">
              Requires an API key (usage-based billing). This is separate from subscriptions like Claude Pro/Max.
            </p>
          </div>

          <div className="space-y-3">
            {PROVIDERS.map(p => (
              <div key={p.provider}>
                <ProviderCard
                  provider={p.provider}
                  label={p.label}
                  onConnected={handleProviderConnected}
                />
                {p.note && <p className="text-neutral-600 text-[10px] mt-1 px-1">{p.note}</p>}
              </div>
            ))}
          </div>

          <p className="text-neutral-600 text-xs">
            Your sensitive data NEVER leaves your machine. oikOS enforces this automatically.
          </p>
        </div>
      )}

      {error && <p className="text-red-400 text-sm">{error}</p>}

      <div className="flex justify-between">
        <button onClick={() => setMode(null)} className="px-4 py-2 border border-neutral-800 text-neutral-400 hover:text-white">
          Back
        </button>
        <div className="flex gap-3">
          <button onClick={onNext} className="px-4 py-2 text-neutral-400 hover:text-white">
            Skip
          </button>
          <button
            onClick={handleNext}
            disabled={!canProceed || saving}
            className="px-6 py-2 bg-amber-400 text-black font-medium hover:bg-amber-300 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {saving ? "Saving..." : "Next"}
          </button>
        </div>
      </div>
    </div>
  );
}
