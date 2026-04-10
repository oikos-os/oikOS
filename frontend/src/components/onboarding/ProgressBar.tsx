const STEPS = ["Identity", "Inference", "Rooms", "Ready"];

export default function ProgressBar({ current }: { current: number }) {
  return (
    <div className="flex gap-2 mb-8">
      {STEPS.map((label, i) => (
        <div key={label} className="flex-1 flex flex-col items-center gap-1">
          <div
            className={`w-full h-1 ${
              i === current
                ? "bg-amber-400"
                : i < current
                  ? "bg-amber-400/20"
                  : "bg-neutral-800"
            }`}
          />
          <span
            className={`text-xs ${
              i === current ? "text-amber-400" : "text-neutral-600"
            }`}
          >
            {label}
          </span>
        </div>
      ))}
    </div>
  );
}
