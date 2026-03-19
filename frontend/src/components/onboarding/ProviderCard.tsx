import { useState } from "react";

type Status = "idle" | "testing" | "connected" | "failed";

interface Props {
  provider: string;
  label: string;
  onConnected: (provider: string) => void;
}

export default function ProviderCard({ provider, label, onConnected }: Props) {
  const [key, setKey] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const [saved, setSaved] = useState(false);

  async function handleTest() {
    if (!key.trim()) return;
    setStatus("testing");
    setErrorMsg("");
    try {
      const res = await fetch("/api/onboarding/providers/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, api_key: key.trim() }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) {
        setStatus("connected");
        // Auto-save on success
        await fetch("/api/onboarding/providers", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider, api_key: key.trim() }),
        });
        setSaved(true);
        onConnected(provider);
      } else {
        setStatus("failed");
        setErrorMsg(data.detail || data.error || "Connection failed");
      }
    } catch {
      setStatus("failed");
      setErrorMsg("Network error");
    }
  }

  return (
    <div className="bg-[#1a1a1a] border border-neutral-800 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-white font-medium">{label}</span>
        {status === "idle" && <span className="text-neutral-600 text-xs">Not configured</span>}
        {status === "testing" && <span className="text-amber-400 text-xs">Testing...</span>}
        {status === "connected" && <span className="text-green-400 text-xs">Connected</span>}
        {status === "failed" && <span className="text-red-400 text-xs">Failed</span>}
      </div>

      <div className="flex gap-2">
        <input
          type="password"
          value={saved ? "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" : key}
          onChange={e => { setKey(e.target.value); setSaved(false); setStatus("idle"); }}
          disabled={saved}
          placeholder="API key"
          className="flex-1 bg-[#0a0a0a] border border-neutral-800 px-3 py-2 text-white placeholder:text-neutral-600 focus:border-amber-400 focus:outline-none text-sm disabled:opacity-50"
        />
        <button
          onClick={handleTest}
          disabled={!key.trim() || status === "testing" || saved}
          className="px-4 py-2 border border-amber-400 text-amber-400 text-sm hover:bg-amber-400/10 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {status === "testing" ? "Testing..." : saved ? "Saved" : "Test"}
        </button>
      </div>

      {status === "failed" && errorMsg && (
        <p className="text-red-400 text-xs">{errorMsg}</p>
      )}
    </div>
  );
}
