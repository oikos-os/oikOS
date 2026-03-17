import type { PipelineTrace as PipelineTraceType } from "../types";

interface Props {
  pipeline: PipelineTraceType | undefined;
  piiScrubbed?: boolean;
}

const STEPS: { key: keyof PipelineTraceType; label: string }[] = [
  { key: "adversarial", label: "ADV" },
  { key: "pii", label: "PII" },
  { key: "cosine_gate", label: "COS" },
  { key: "contradiction", label: "NLI" },
  { key: "coherence", label: "COH" },
  { key: "output_filter", label: "FLT" },
];

export default function PipelineTrace({ pipeline, piiScrubbed }: Props) {
  if (!pipeline) return null;

  return (
    <div className="flex gap-1.5 text-xs font-mono" data-testid="pipeline-trace">
      {STEPS.map(({ key, label }) => {
        const fired = pipeline[key];
        const scrubbed = key === "pii" && piiScrubbed;
        return (
          <span
            key={key}
            className={
              fired
                ? scrubbed
                  ? "text-red-400"
                  : "text-amber-500"
                : "text-neutral-600"
            }
          >
            {label}
          </span>
        );
      })}
    </div>
  );
}
