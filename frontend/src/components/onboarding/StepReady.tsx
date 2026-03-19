import { useState } from "react";

interface Props {
  selectedModel: { provider: string; model: string } | null;
  configuredProviders: string[];
  selectedRoom: string | null;
  onComplete: () => void;
}

export default function StepReady({ selectedModel, configuredProviders, selectedRoom, onComplete }: Props) {
  const [completing, setCompleting] = useState(false);

  async function handleComplete() {
    setCompleting(true);
    try {
      await fetch("/api/onboarding/complete", { method: "POST" });
      onComplete();
    } catch {
      onComplete();
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl text-white mb-1">Ready</h2>
        <p className="text-neutral-400 text-sm">Here is what you configured.</p>
      </div>

      <div className="space-y-3">
        <div className="bg-[#1a1a1a] border border-neutral-800 p-4 flex justify-between">
          <span className="text-neutral-400">Local model</span>
          <span className="text-white">
            {selectedModel ? `${selectedModel.provider} / ${selectedModel.model}` : "None -- configure later"}
          </span>
        </div>

        <div className="bg-[#1a1a1a] border border-neutral-800 p-4 flex justify-between">
          <span className="text-neutral-400">Cloud providers</span>
          <span className="text-white">
            {configuredProviders.length > 0 ? configuredProviders.join(", ") : "None"}
          </span>
        </div>

        <div className="bg-[#1a1a1a] border border-neutral-800 p-4 flex justify-between">
          <span className="text-neutral-400">Room</span>
          <span className="text-white">
            {selectedRoom || "Home only"}
          </span>
        </div>
      </div>

      <p className="text-neutral-600 text-sm text-center">Your data stays on your machine.</p>

      <div className="flex justify-center">
        <button
          onClick={handleComplete}
          disabled={completing}
          className="px-10 py-3 bg-amber-400 text-black font-medium text-lg hover:bg-amber-300 disabled:opacity-40"
        >
          {completing ? "Starting..." : "Start Chatting"}
        </button>
      </div>
    </div>
  );
}
