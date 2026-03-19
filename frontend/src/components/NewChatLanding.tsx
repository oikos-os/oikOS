import { useCallback, useEffect, useRef, useState } from "react";
import { IconAttach, IconChevronDown, IconMicrophone } from "./icons";

interface ModelInfo {
  name: string;
  size?: number;
  type?: string;
}

interface Props {
  onSend: (query: string, opts?: { model?: string; attachedFiles?: { name: string; content: string }[] }) => void;
  disabled: boolean;
}

const QUICK_OPTIONS = [
  "Code Generation", "Writing Assistance", "System Analysis",
  "Vault Search", "Debug & Fix", "Architecture",
];

const TIPS = [
  "Ask me anything about the OIKOS system...",
  "Debug a module, query the vault, run the gauntlet...",
  "What can I help you build today?",
];

const HINTS = [
  "Search the vault for any knowledge fragment...",
  "Try: \"What assertions define my identity?\"",
  "Try: \"Run the gauntlet\" to stress-test the system",
  "Try: \"Summarize today's activity feed\"",
  "Tip: Use Shift+Enter for multiline input",
  "Tip: Switch models with the selector below",
  "Try: \"What is my current FSM state?\"",
  "Try: \"How many credits remain?\"",
  "Tip: Attach files for context-aware analysis",
  "Try: \"Explain the OIKOS architecture\"",
  "Try: \"What happened in the last session?\"",
  "Try: \"Check vault health and stats\"",
];

export default function NewChatLanding({ onSend, disabled }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [modelOpen, setModelOpen] = useState(false);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("qwen2.5:14b");
  const [attachedFiles, setAttachedFiles] = useState<{ name: string; content: string }[]>([]);
  const [hintIdx, setHintIdx] = useState(() => Math.floor(Math.random() * HINTS.length));
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [sugLoading, setSugLoading] = useState(false);
  const [sugError, setSugError] = useState<string | null>(null);
  const sugAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const id = setInterval(() => setHintIdx((i) => (i + 1) % HINTS.length), 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => () => { sugAbortRef.current?.abort(); }, []);

  useEffect(() => {
    fetch("/api/models")
      .then((r) => r.ok ? r.json() : { local: [], cloud: [] })
      .then((data) => {
        const all: ModelInfo[] = [
          ...(data.local || []),
          ...(data.cloud || []),
        ];
        setModels(all);
        if (all.length > 0 && !all.find((m) => m.name === selectedModel)) {
          setSelectedModel(all[0].name);
        }
      })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchSuggestions = useCallback(async (category: string) => {
    sugAbortRef.current?.abort();
    if (activeCategory === category) {
      setActiveCategory(null);
      setSuggestions([]);
      return;
    }
    setActiveCategory(category);
    setSuggestions([]);
    setSugError(null);
    setSugLoading(true);
    const controller = new AbortController();
    sugAbortRef.current = controller;
    try {
      const res = await fetch(`/api/chat/suggestions?category=${encodeURIComponent(category)}`, { signal: controller.signal });
      if (!res.ok || !res.body) { setSugLoading(false); setSugError("Failed to fetch suggestions"); return; }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let raw = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const msg = JSON.parse(line.slice(6));
            if (msg.error) { setSugError("Inference unavailable"); }
            if (msg.delta) {
              raw += msg.delta;
              setSuggestions(raw.split("\n").map((s: string) => s.trim()).filter(Boolean));
            }
          } catch { /* partial JSON */ }
        }
      }
    } catch { /* aborted */ }
    setSugLoading(false);
  }, [activeCategory]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        const val = ref.current?.value.trim();
        if (val) {
          onSend(val, { model: selectedModel, attachedFiles: attachedFiles.length > 0 ? attachedFiles : undefined });
          if (ref.current) ref.current.value = "";
          setAttachedFiles([]);
        }
      }
    },
    [onSend, selectedModel, attachedFiles],
  );

  return (
    <div className="flex-1 flex flex-col items-center px-4 overflow-y-auto" data-testid="new-chat-landing">
      <div className="max-w-2xl w-full my-auto py-8">
        {/* Greeting */}
        <div className="mb-8 text-center">
          <div className="flex items-center justify-center gap-2 mb-3">
            <span className="w-2.5 h-2.5 rounded-full bg-green-500" />
            <span className="text-lg font-bold tracking-widest text-white">oikOS</span>
          </div>
          <p className="text-neutral-400 text-sm">{TIPS[Math.floor(Date.now() / 60000) % TIPS.length]}</p>
        </div>

        {/* Prompt box */}
        <div className="bg-[#242424] rounded-2xl p-4 mb-4">
          <textarea
            ref={ref}
            rows={3}
            disabled={disabled}
            placeholder={disabled ? "Waiting for response..." : HINTS[hintIdx]}
            className="w-full bg-transparent text-white text-base resize-none outline-none placeholder:text-neutral-500"
            onKeyDown={handleKeyDown}
            data-testid="landing-input"
          />

          <div className="flex items-center justify-between mt-2">
            {/* Left: attach */}
            <div className="relative flex items-center gap-1">
              <button
                onClick={() => fileInputRef.current?.click()}
                className="p-1.5 text-neutral-500 hover:text-neutral-300 transition-colors"
                title="Attach file"
              >
                <IconAttach />
              </button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={(e) => {
                  const files = e.target.files;
                  if (!files) return;
                  Array.from(files).forEach((file) => {
                    const reader = new FileReader();
                    reader.onload = () => {
                      setAttachedFiles((prev) => [...prev, { name: file.name, content: reader.result as string }]);
                    };
                    reader.readAsText(file);
                  });
                  e.target.value = "";
                }}
              />
              {attachedFiles.map((f, i) => (
                <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 text-xs bg-[#333] text-neutral-300 rounded">
                  {f.name}
                  <button onClick={() => setAttachedFiles((prev) => prev.filter((_, j) => j !== i))} className="text-neutral-500 hover:text-white">&times;</button>
                </span>
              ))}
            </div>

            {/* Right: model selector + voice */}
            <div className="flex items-center gap-2">
              <div className="relative">
                <button
                  onClick={() => setModelOpen(!modelOpen)}
                  className="flex items-center gap-1 px-2 py-1 text-xs text-neutral-400 hover:text-neutral-300 transition-colors"
                  data-testid="model-selector"
                >
                  <span>{selectedModel}</span>
                  <IconChevronDown className="w-3 h-3" />
                </button>
                {modelOpen && (
                  <div className="absolute bottom-full right-0 mb-1 bg-[#2a2a2a] border border-neutral-700/50 rounded-lg py-1 min-w-[160px] z-10">
                    {models.map((m) => (
                      <button
                        key={m.name}
                        onClick={() => { setSelectedModel(m.name); setModelOpen(false); }}
                        className={`block w-full text-left px-3 py-1.5 text-sm ${m.name === selectedModel ? "text-white bg-[#333]" : "text-neutral-400 hover:text-white hover:bg-[#333]"}`}
                      >
                        {m.name}{m.type === "cloud" ? " (cloud)" : ""}
                      </button>
                    ))}
                    {models.length === 0 && (
                      <span className="block px-3 py-1.5 text-sm text-neutral-500">No models found</span>
                    )}
                  </div>
                )}
              </div>
              <button className="p-1.5 text-neutral-500 hover:text-neutral-300 transition-colors" title="Voice mode">
                <IconMicrophone />
              </button>
            </div>
          </div>
        </div>

        {/* Quick options */}
        <div className="flex flex-wrap gap-2 justify-center">
          {QUICK_OPTIONS.map((label) => (
            <button
              key={label}
              onClick={() => fetchSuggestions(label)}
              className={`px-3 py-1.5 text-xs rounded-full transition-colors ${
                activeCategory === label
                  ? "bg-amber-600/20 text-amber-400 border border-amber-600/40"
                  : "text-neutral-400 bg-[#242424] hover:bg-[#2a2a2a] hover:text-neutral-300"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Suggestions */}
        {activeCategory && (
          <div className="mt-3 space-y-1.5 max-w-2xl">
            {sugLoading && suggestions.length === 0 && !sugError && (
              <p className="text-xs text-amber-400 text-center animate-pulse">Generating suggestions...</p>
            )}
            {sugError && (
              <p className="text-xs text-red-400 text-center">{sugError}</p>
            )}
            {suggestions.map((s, i) => (
              <button
                key={i}
                onClick={() => {
                  if (ref.current) ref.current.value = s;
                  ref.current?.focus();
                }}
                className="block w-full text-left px-4 py-2.5 text-sm text-neutral-300 bg-[#242424] border border-neutral-700/30 hover:border-amber-600/50 hover:text-white transition-colors"
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
