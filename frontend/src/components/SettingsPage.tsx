import { useCallback, useEffect, useState } from "react";
import type { DetectedBackend } from "../types";

interface Settings {
  [key: string]: unknown;
}

const SECTIONS: { title: string; keys: { key: string; label: string; type: "text" | "number" }[] }[] = [
  {
    title: "GENERAL",
    keys: [
      { key: "inference_model", label: "Inference Model", type: "text" },
      { key: "cloud_model", label: "Cloud Model", type: "text" },
      { key: "cloud_routing_posture", label: "Cloud Posture", type: "text" },
    ],
  },
  {
    title: "MODEL",
    keys: [
      { key: "default_token_budget", label: "Token Budget", type: "number" },
      { key: "inference_temperature", label: "Temperature", type: "number" },
      { key: "inference_top_p", label: "Top-P", type: "number" },
      { key: "inference_max_tokens", label: "Max Tokens", type: "number" },
      { key: "embed_batch_size", label: "Embed Batch Size", type: "number" },
    ],
  },
  {
    title: "SAFETY",
    keys: [
      { key: "pii_confidence_threshold", label: "PII Threshold", type: "number" },
      { key: "routing_confidence_threshold", label: "Routing Threshold", type: "number" },
      { key: "credits_monthly_cap", label: "Monthly Credit Cap", type: "number" },
    ],
  },
];

function formatSize(bytes: number): string {
  if (bytes <= 0) return "—";
  const gb = bytes / 1_073_741_824;
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${(bytes / 1_048_576).toFixed(0)} MB`;
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");
  const [backends, setBackends] = useState<DetectedBackend[]>([]);
  const [scanning, setScanning] = useState(false);
  const [crtEnabled, setCrtEnabled] = useState(() => {
    try { return localStorage.getItem("oikos-crt-effects") !== "0"; } catch { return true; }
  });

  const scanBackends = useCallback(async () => {
    setScanning(true);
    try {
      const res = await fetch("/api/onboarding/detect-backends");
      if (res.ok) setBackends(await res.json());
    } catch { /* ignore */ }
    setScanning(false);
  }, []);

  useEffect(() => {
    fetch("/api/settings")
      .then((r) => r.ok ? r.json() : {})
      .then(setSettings)
      .catch(() => {});
    scanBackends();
  }, [scanBackends]);

  const handleSave = useCallback(async (key: string, value: unknown) => {
    setSaving(key);
    setStatus("");
    try {
      const res = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, value }),
      });
      if (res.ok) {
        setSettings((prev) => ({ ...prev, [key]: value }));
        setStatus(`Saved ${key}`);
      } else {
        const data = await res.json();
        setStatus(`Error: ${data.detail || "Failed"}`);
      }
    } catch {
      setStatus("Network error");
    } finally {
      setSaving(null);
    }
  }, []);

  return (
    <div className="flex-1 overflow-y-auto p-4 max-w-3xl mx-auto w-full" data-testid="settings-page">
      <h2 className="text-lg font-bold tracking-widest mb-4 phosphor-glow-subtle">SETTINGS</h2>

      {status && (
        <div className="mb-3 px-3 py-1.5 text-xs bg-[var(--bg-elevated)] border border-[var(--border-subtle)]">
          {status}
        </div>
      )}

      {SECTIONS.map((section) => (
        <div key={section.title} className="mb-6">
          <h3 className="text-sm font-bold tracking-wider text-[var(--accent)] mb-2">{section.title}</h3>
          <div className="space-y-2">
            {section.keys.map(({ key, label, type }) => (
              <div key={key} className="flex items-center gap-3 bg-[var(--bg-tertiary)] px-3 py-2 border border-[var(--border-subtle)]">
                <label className="text-sm text-[var(--text-secondary)] w-48 shrink-0">{label}</label>
                <input
                  type={type}
                  step={type === "number" ? "any" : undefined}
                  value={settings[key] != null ? String(settings[key]) : ""}
                  onChange={(e) => {
                    const val = type === "number" ? Number(e.target.value) : e.target.value;
                    setSettings((prev) => ({ ...prev, [key]: val }));
                  }}
                  className="flex-1 bg-[var(--bg-elevated)] text-[var(--text-primary)] px-2 py-1 text-sm outline-none border border-[var(--border-subtle)] focus:border-[var(--accent)]"
                />
                <button
                  onClick={() => handleSave(key, settings[key])}
                  disabled={saving === key}
                  className="px-3 py-1 text-xs bg-[var(--accent)] text-black font-bold hover:opacity-90 disabled:opacity-50"
                >
                  {saving === key ? "..." : "SAVE"}
                </button>
              </div>
            ))}
          </div>
        </div>
      ))}

      <div className="mb-6" data-testid="display-settings">
        <h3 className="text-sm font-bold tracking-wider text-[var(--accent)] mb-2">DISPLAY</h3>
        <div className="flex items-center justify-between bg-[var(--bg-tertiary)] px-3 py-2 border border-[var(--border-subtle)]">
          <label className="text-sm text-[var(--text-secondary)]">CRT Effects</label>
          <button
            data-testid="crt-toggle"
            onClick={() => {
              const next = !crtEnabled;
              setCrtEnabled(next);
              document.documentElement.style.setProperty("--effects-enabled", next ? "1" : "0");
              document.documentElement.style.setProperty("--scanline-opacity", next ? "0.03" : "0");
              document.documentElement.style.setProperty("--flicker-play", next ? "running" : "paused");
              try { localStorage.setItem("oikos-crt-effects", next ? "1" : "0"); } catch { /* */ }
            }}
            className={`w-10 h-5 transition-colors ${crtEnabled ? "bg-[var(--accent)]" : "bg-[var(--bg-elevated)]"} relative`}
          >
            <span className={`block w-4 h-4 bg-white absolute top-0.5 transition-transform ${crtEnabled ? "translate-x-5" : "translate-x-0.5"}`} />
          </button>
        </div>
      </div>

      <div className="mb-6" data-testid="local-backends">
        <div className="flex items-center gap-3 mb-2">
          <h3 className="text-sm font-bold tracking-wider text-[var(--accent)]">LOCAL BACKENDS</h3>
          <button
            onClick={scanBackends}
            disabled={scanning}
            className="px-3 py-1 text-xs bg-[var(--bg-tertiary)] text-[var(--text-secondary)] border border-[var(--border-subtle)] hover:border-[var(--accent)] disabled:opacity-50"
          >
            {scanning ? "SCANNING..." : "RESCAN"}
          </button>
        </div>

        {backends.length === 0 && !scanning && (
          <div className="bg-[#1a1a1a] px-3 py-3 border border-[var(--border-subtle)] text-sm text-[var(--text-secondary)]">
            No local backends detected. Install Ollama at{" "}
            <a href="https://ollama.com" target="_blank" rel="noreferrer" className="text-[var(--accent)] hover:underline">ollama.com</a>
          </div>
        )}

        <div className="space-y-2">
          {backends.map((b) => (
            <div key={b.backend} className="bg-[#1a1a1a] px-3 py-3 border border-[var(--border-subtle)]">
              <div className="flex items-center justify-between mb-1">
                <div>
                  <span className="text-sm font-bold text-[var(--text-primary)]">{b.display_name || b.backend}</span>
                  <span className="text-xs text-[var(--text-secondary)] ml-2">:{b.port}</span>
                </div>
                <button
                  onClick={() => handleSave("provider_default", b.backend)}
                  disabled={saving === "provider_default"}
                  className="px-3 py-1 text-xs bg-[var(--accent)] text-black font-bold hover:opacity-90 disabled:opacity-50"
                >
                  SET AS DEFAULT
                </button>
              </div>
              {b.models.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-2">
                  {b.models.map((m) => (
                    <span key={m.name} className="text-xs bg-[var(--bg-tertiary)] px-2 py-0.5 text-[var(--text-secondary)] border border-[var(--border-subtle)]">
                      {m.name} {formatSize(m.size_bytes)}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
