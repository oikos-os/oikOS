/**
 * T-119: Poll /api/notifications/pending and surface items as toasts.
 *
 * Mirrors the TUI NotificationBar pattern: poll every 3s, track the latest
 * timestamp seen, pass only new items to the caller via addToasts().
 *
 * Severity mapping: backend uses Textual strings (information/warning/error/critical),
 * ToastLevel uses (info/warning/error/critical).
 */
import { useCallback, useEffect, useRef } from "react";
import type { Toast, ToastLevel } from "./useNotifications";

const POLL_MS = 3_000;

/** Backend notification shape from /api/notifications/pending */
interface PendingItem {
  timestamp: number;
  message: string;
  title: string;
  severity: string;
  timeout_seconds: number;
  event_key: string;
}

function severityToLevel(severity: string): ToastLevel {
  switch (severity) {
    case "warning":  return "warning";
    case "error":    return "error";
    case "critical": return "critical";
    default:         return "info";   // "information" → info
  }
}

let _nextId = 1000;  // Offset from useNotifications counter to avoid id collisions

/**
 * Poll /api/notifications/pending every 3s.
 *
 * @param addToasts - callback from useNotifications to append new toasts
 */
export function usePendingNotifications(addToasts: (toasts: Toast[]) => void): void {
  const lastSeenRef = useRef<number>(0);
  // Keep a stable ref to addToasts to avoid stale-closure effect re-runs
  const addToastsRef = useRef(addToasts);
  useEffect(() => { addToastsRef.current = addToasts; }, [addToasts]);

  const poll = useCallback(async () => {
    try {
      const url = `/api/notifications/pending?since=${lastSeenRef.current}`;
      const res = await fetch(url);
      if (!res.ok) return;
      const body = await res.json() as { pending: PendingItem[] };
      const items = body.pending ?? [];
      if (items.length === 0) return;

      // Advance the cursor
      const maxTs = Math.max(...items.map((n) => n.timestamp));
      lastSeenRef.current = maxTs;

      const newToasts: Toast[] = items.map((n) => ({
        id: `pending-${_nextId++}`,
        level: severityToLevel(n.severity),
        title: n.title,
        message: n.message,
        persistent: n.severity === "critical",
        timestamp: Date.now(),
      }));

      addToastsRef.current(newToasts);
    } catch {
      // Network errors are silent — the endpoint is best-effort
    }
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => clearInterval(id);
  }, [poll]);
}
