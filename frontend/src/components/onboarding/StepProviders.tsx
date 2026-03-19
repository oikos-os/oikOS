import { useCallback } from "react";
import ProviderCard from "./ProviderCard";

const PROVIDERS = [
  { provider: "anthropic", label: "Anthropic (Claude)" },
  { provider: "openai", label: "OpenAI (GPT)" },
  { provider: "gemini", label: "Google (Gemini)" },
];

interface Props {
  configuredProviders: string[];
  setConfiguredProviders: (v: string[]) => void;
  onNext: () => void;
  onBack: () => void;
}

export default function StepProviders({ configuredProviders, setConfiguredProviders, onNext, onBack }: Props) {
  const handleConnected = useCallback((provider: string) => {
    setConfiguredProviders([...new Set([...configuredProviders, provider])]);
  }, [configuredProviders, setConfiguredProviders]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl text-white mb-1">Cloud providers (optional)</h2>
        <p className="text-neutral-400 text-sm">
          Connect cloud LLM providers for complex queries. Local models handle everything else.
        </p>
      </div>

      <div className="space-y-3">
        {PROVIDERS.map(p => (
          <ProviderCard
            key={p.provider}
            provider={p.provider}
            label={p.label}
            onConnected={handleConnected}
          />
        ))}
      </div>

      <p className="text-neutral-600 text-xs">
        Your sensitive data NEVER leaves your machine. API keys are stored locally in .env and are never transmitted to oikOS servers.
      </p>

      <div className="flex justify-between">
        <button onClick={onBack} className="px-4 py-2 border border-neutral-800 text-neutral-400 hover:text-white">
          Back
        </button>
        <div className="flex gap-3">
          <button onClick={onNext} className="px-4 py-2 text-neutral-400 hover:text-white">
            Skip
          </button>
          <button
            onClick={onNext}
            className="px-6 py-2 bg-amber-400 text-black font-medium hover:bg-amber-300"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
