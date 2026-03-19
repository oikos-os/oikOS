import { useCallback, useEffect, useRef, useState } from "react";
import type { EventRecord } from "../types";

export type ToastLevel = "info" | "warning" | "error" | "critical";

export interface Toast {
  id: string;
  level: ToastLevel;
  title: string;
  message: string;
  persistent: boolean;
  timestamp: number;
}

export interface NotificationPrefs {
  interventions: boolean;
  gauntletRegressions: boolean;
  consolidation: boolean;
  errors: boolean;
}

const DEFAULT_PREFS: NotificationPrefs = {
  interventions: true,
  gauntletRegressions: true,
  consolidation: true,
  errors: true,
};

let _nextId = 0;

function eventToToast(ev: EventRecord, prefs: NotificationPrefs): Toast | null {
  // INTERVENTION escalation
  if (ev.category === "agent" && ev.type === "intervention") {
    if (!prefs.interventions) return null;
    return {
      id: `toast-${_nextId++}`,
      level: "critical",
      title: "INTERVENTION",
      message: String(ev.data?.message ?? "Escalation triggered"),
      persistent: true,
      timestamp: Date.now(),
    };
  }

  // Gauntlet regression
  if (ev.category === "agent" && ev.type === "gauntlet_complete") {
    const regressions = Number(ev.data?.regressions ?? 0);
    if (regressions > 0 && prefs.gauntletRegressions) {
      return {
        id: `toast-${_nextId++}`,
        level: "warning",
        title: "GAUNTLET REGRESSION",
        message: `${regressions} regression(s) detected`,
        persistent: false,
        timestamp: Date.now(),
      };
    }
  }

  // Consolidation proposals
  if (ev.category === "agent" && ev.type === "consolidation_complete") {
    const proposals = Number(ev.data?.proposals_generated ?? 0);
    if (proposals > 0 && prefs.consolidation) {
      return {
        id: `toast-${_nextId++}`,
        level: "info",
        title: "CONSOLIDATION",
        message: `${proposals} new proposal(s) pending review`,
        persistent: false,
        timestamp: Date.now(),
      };
    }
  }

  // Errors
  if (ev.category === "error") {
    if (!prefs.errors) return null;
    return {
      id: `toast-${_nextId++}`,
      level: "error",
      title: "ERROR",
      message: String(ev.data?.message ?? ev.type),
      persistent: false,
      timestamp: Date.now(),
    };
  }

  return null;
}

export function useNotifications(events: EventRecord[] | null, prefs?: Partial<NotificationPrefs>) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const mergedPrefs = { ...DEFAULT_PREFS, ...prefs };
  const seenRef = useRef(new Set<string>());

  // Process new events into toasts
  useEffect(() => {
    if (!events || events.length === 0) return;

    const newToasts: Toast[] = [];
    for (const ev of events) {
      const key = `${ev.timestamp}-${ev.category}-${ev.type}`;
      if (seenRef.current.has(key)) continue;
      seenRef.current.add(key);

      const toast = eventToToast(ev, mergedPrefs);
      if (toast) newToasts.push(toast);
    }

    if (newToasts.length > 0) {
      setToasts((prev) => [...prev, ...newToasts]);
    }
  }, [events, mergedPrefs.interventions, mergedPrefs.gauntletRegressions, mergedPrefs.consolidation, mergedPrefs.errors]);

  // Auto-dismiss non-persistent toasts after 10s
  useEffect(() => {
    if (toasts.length === 0) return;

    const timer = setInterval(() => {
      const now = Date.now();
      setToasts((prev) =>
        prev.filter((t) => t.persistent || now - t.timestamp < 10_000),
      );
    }, 1000);

    return () => clearInterval(timer);
  }, [toasts.length]);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return { toasts, dismiss };
}
