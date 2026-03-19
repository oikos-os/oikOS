import { useCallback, useEffect, useRef, useState } from "react";
import { IconAttach, IconChevronDown } from "./icons";

interface ModelInfo {
  name: string;
  size?: number;
  type?: string;
}

interface Props {
  onSend: (query: string, opts?: { model?: string; attachedFiles?: { name: string; content: string }[] }) => void;
  disabled: boolean;
}

export default function MessageInput({ onSend, disabled }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [modelOpen, setModelOpen] = useState(false);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("qwen2.5:14b");
  const [attachedFiles, setAttachedFiles] = useState<{ name: string; content: string }[]>([]);

  useEffect(() => {
    fetch("/api/models")
      .then((r) => r.ok ? r.json() : { local: [], cloud: [] })
      .then((data) => {
        const all: ModelInfo[] = [...(data.local || []), ...(data.cloud || [])];
        setModels(all);
        if (all.length > 0 && !all.find((m) => m.name === selectedModel)) {
          setSelectedModel(all[0].name);
        }
      })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
      if (e.key === "Escape") {
        if (ref.current) ref.current.value = "";
      }
    },
    [onSend, selectedModel, attachedFiles],
  );

  useEffect(() => {
    function handleGlobal(e: KeyboardEvent) {
      if (e.key === "/" && document.activeElement !== ref.current) {
        e.preventDefault();
        ref.current?.focus();
      }
    }
    window.addEventListener("keydown", handleGlobal);
    return () => window.removeEventListener("keydown", handleGlobal);
  }, []);

  return (
    <div className="border-t border-neutral-700/50 p-3">
      <div className="bg-[#242424] rounded-2xl p-3">
        <textarea
          ref={ref}
          rows={2}
          disabled={disabled}
          placeholder={disabled ? "Waiting for response..." : "Type a message... (/ to focus, Shift+Enter for newline)"}
          className="w-full bg-transparent text-white text-base resize-none outline-none placeholder:text-neutral-500"
          onKeyDown={handleKeyDown}
          data-testid="chat-input"
        />

        <div className="flex items-center justify-between mt-1">
          {/* Left: attach */}
          <div className="flex items-center gap-1">
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

          {/* Right: model selector */}
          <div className="relative">
            <button
              onClick={() => setModelOpen(!modelOpen)}
              className="flex items-center gap-1 px-2 py-1 text-xs text-neutral-400 hover:text-neutral-300 transition-colors"
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
        </div>
      </div>
    </div>
  );
}
