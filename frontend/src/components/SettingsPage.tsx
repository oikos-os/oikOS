import { useCallback, useEffect, useState } from "react";

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

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");

  useEffect(() => {
    fetch("/api/settings")
      .then((r) => r.ok ? r.json() : {})
      .then(setSettings)
      .catch(() => {});
  }, []);

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
      <h2 className="text-lg font-bold tracking-widest mb-4">SETTINGS</h2>

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
    </div>
  );
}
