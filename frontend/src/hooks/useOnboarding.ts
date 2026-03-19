import { useState, useCallback } from "react";
import type { DetectedBackend } from "../types";

export function useOnboarding() {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [backends, setBackends] = useState<DetectedBackend[]>([]);
  const [selectedModel, setSelectedModel] = useState<{ provider: string; model: string } | null>(null);
  const [configuredProviders, setConfiguredProviders] = useState<string[]>([]);
  const [selectedRoom, setSelectedRoom] = useState<string | null>(null);

  const next = useCallback(() => setStep(s => Math.min(s + 1, 3)), []);
  const back = useCallback(() => setStep(s => Math.max(s - 1, 0)), []);

  return {
    step, setStep, next, back,
    name, setName, description, setDescription,
    backends, setBackends,
    selectedModel, setSelectedModel,
    configuredProviders, setConfiguredProviders,
    selectedRoom, setSelectedRoom,
  };
}
