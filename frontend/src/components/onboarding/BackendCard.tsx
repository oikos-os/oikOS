import type { DetectedBackend } from "../../types";

function formatGB(bytes: number): string {
  return (bytes / 1_073_741_824).toFixed(1) + " GB";
}

interface Props {
  backend: DetectedBackend;
  selectedModel: string | null;
  onSelect: (provider: string, model: string) => void;
}

export default function BackendCard({ backend, selectedModel, onSelect }: Props) {
  return (
    <div className="bg-[#1a1a1a] border border-neutral-800 p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-white font-medium">{backend.backend}</span>
        <span className="text-neutral-600 text-xs">:{backend.port}</span>
      </div>
      {backend.models.length === 0 ? (
        <p className="text-neutral-600 text-sm">No models installed</p>
      ) : (
        <div className="space-y-2">
          {backend.models.map(m => {
            const value = `${backend.backend}::${m.name}`;
            return (
              <label
                key={m.name}
                className="flex items-center gap-3 p-2 hover:bg-neutral-800/50 cursor-pointer"
              >
                <input
                  type="radio"
                  name="model-select"
                  checked={selectedModel === value}
                  onChange={() => onSelect(backend.backend, m.name)}
                  className="accent-amber-400"
                />
                <span className="text-white text-sm flex-1">{m.name}</span>
                <span className="text-neutral-600 text-xs">{formatGB(m.size_bytes)}</span>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}
