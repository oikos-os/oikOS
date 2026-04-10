import { useEffect, useState } from "react";
import { THINKING_INDICATORS } from "../constants/thinking";

export default function ThinkingIndicator() {
  const [index, setIndex] = useState(() => Math.floor(Math.random() * THINKING_INDICATORS.length));

  useEffect(() => {
    const interval = setInterval(() => {
      setIndex((prev) => (prev + 1) % THINKING_INDICATORS.length);
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  const effectsEnabled =
    typeof document !== "undefined" &&
    getComputedStyle(document.documentElement).getPropertyValue("--effects-enabled").trim() === "1";

  if (!effectsEnabled) {
    return (
      <div data-testid="thinking-indicator" className="py-2 px-4">
        <span className="text-[var(--text-muted)] text-sm">Thinking...</span>
      </div>
    );
  }

  return (
    <div data-testid="thinking-indicator" className="py-3 px-4 flex flex-col items-start gap-1">
      <span className="thinking-dot">{"\u25cf"}</span>
      <span className="thinking-text">{THINKING_INDICATORS[index]}</span>
    </div>
  );
}
