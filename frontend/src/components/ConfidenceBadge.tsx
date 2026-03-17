interface Props {
  confidence: number | null | undefined;
}

export default function ConfidenceBadge({ confidence }: Props) {
  if (confidence == null) return null;

  let color = "text-green-500";
  let label = "HIGH";
  if (confidence < 30) {
    color = "text-red-500";
    label = "LOW";
  } else if (confidence < 60) {
    color = "text-amber-500";
    label = "MED";
  }

  return (
    <span className={`text-xs tracking-wider ${color}`} data-testid="confidence-badge">
      {label} {confidence.toFixed(0)}
    </span>
  );
}
