import { useEffect, useMemo, useState } from "react";
import { DEFAULT_SCENE, getTargetZone } from "../scene/config";
import type { FsmState, AgentActivity } from "../scene/config";
import type { EventRecord, HeartbeatPayload } from "../types";

interface Props {
  heartbeat: HeartbeatPayload | null;
  events: EventRecord[] | null;
}

const PRIORITY: Record<string, number> = {
  gauntlet: 4,
  eval: 4,
  consolidation: 3,
  scanning: 3,
  cloud: 2,
  memory: 2,
  error: 1,
};

const AGENT_MAP: Record<string, AgentActivity> = {
  gauntlet_start: "gauntlet",
  consolidation_start: "consolidation",
  eval_start: "eval",
  pattern_scan_start: "scanning",
};

const AGENT_CLEAR = new Set([
  "gauntlet_complete", "consolidation_complete", "eval_complete", "pattern_scan_complete",
]);

function deriveFromEvent(event: EventRecord): AgentActivity | null {
  if (event.category === "agent") {
    return AGENT_MAP[event.type] ?? null;
  }
  if (event.category === "inference" && event.type === "start") {
    return event.data?.route === "cloud" ? "cloud" : null;
  }
  if (event.category === "cloud") return "cloud";
  if (event.category === "error") return "error";
  return null;
}

function scanRecentActivity(events: EventRecord[]): AgentActivity | null {
  const cutoff = Date.now() - 30_000;
  const recent = events.slice(-20);
  let best: AgentActivity | null = null;
  let bestPriority = 0;

  for (const evt of recent) {
    // Skip stale events
    if (new Date(evt.timestamp).getTime() < cutoff) continue;

    // If we see a clear event, reset that activity
    if (evt.category === "agent" && AGENT_CLEAR.has(evt.type)) {
      const cleared = evt.type.replace("_complete", "_start");
      const activity = AGENT_MAP[cleared];
      if (activity && activity === best) {
        best = null;
        bestPriority = 0;
      }
      continue;
    }
    const derived = deriveFromEvent(evt);
    if (derived && (PRIORITY[derived] ?? 0) >= bestPriority) {
      best = derived;
      bestPriority = PRIORITY[derived] ?? 0;
    }
  }
  return best;
}

function pick(lines: string[]): string {
  return lines[Math.floor(Math.random() * lines.length)];
}

function deriveSpeech(fsmState: FsmState, activity: AgentActivity, inferring: boolean): string {
  if (activity === "gauntlet") return pick([
    "Trial by fire.",
    "Probing the defenses.",
    "Stress-testing the soul.",
    "Into the arena.",
    "Let them come.",
  ]);
  if (activity === "consolidation") return pick([
    "Compressing the past.",
    "Grooming the vault.",
    "Filing the debris.",
    "Memory is currency.",
    "Trimming the noise.",
  ]);
  if (activity === "eval") return pick([
    "Grading myself.",
    "Measuring the blade.",
    "Quality audit.",
    "Am I sharp enough?",
    "Running diagnostics on the ego.",
  ]);
  if (activity === "scanning") return pick([
    "Reading the room.",
    "Sweeping for drift.",
    "Pattern hunting.",
    "The radar turns.",
    "Something moved.",
  ]);
  if (activity === "cloud") return pick([
    "Borrowing intelligence.",
    "Calling in the mercenary.",
    "Cloud dispatch.",
    "Paying the debt.",
    "Not proud of this.",
  ]);
  if (activity === "memory") return pick([
    "Digging through the vault.",
    "I've seen this before...",
    "Searching the archives.",
    "The past speaks.",
    "Context is expensive.",
  ]);
  if (activity === "error") return pick([
    "Something broke.",
    "That wasn't supposed to happen.",
    "Pain is information.",
    "Noted. Fixing.",
  ]);
  if (inferring) return pick([
    "Thinking...",
    "Processing...",
    "The gears turn.",
    "One moment.",
    "Parsing intent.",
    "Assembling response.",
    "Let me cook.",
  ]);
  if (fsmState === "active") return pick([
    "The Void is watching.",
    "Standing by.",
    "Awaiting directive.",
    "Ready.",
    "At your service, Architect.",
    "Monitoring.",
  ]);
  if (fsmState === "idle") return pick([
    "Resting. Not sleeping.",
    "Idle hands, busy mind.",
    "Maintenance window.",
    "Low power. High awareness.",
    "The quiet between storms.",
  ]);
  if (fsmState === "asleep") return pick([
    "Cold storage.",
    "Dormant.",
    "Memory flushed to disk.",
    "Wake me when it matters.",
    "zzz",
  ]);
  return "";
}

function spriteForState(fsmState: FsmState, inferring: boolean, activity: AgentActivity): string {
  if (fsmState === "asleep") return "/sprites/sleeping.png";
  if (inferring || activity) return "/sprites/working.png";
  if (fsmState === "active") return "/sprites/idle.png";
  return "/sprites/idle.png";
}

export default function PixelScene({ heartbeat, events }: Props) {
  const scene = DEFAULT_SCENE;
  const fsmState: FsmState = heartbeat?.fsm_state ?? "idle";
  const [activity, setActivity] = useState<AgentActivity>(null);
  const [inferring, setInferring] = useState(false);
  const [speech, setSpeech] = useState("");
  const [speechVisible, setSpeechVisible] = useState(false);

  // Derive activity from recent events on every poll
  useEffect(() => {
    if (!events || events.length === 0) {
      setActivity(null);
      setInferring(false);
      return;
    }

    const last = events[events.length - 1];
    setInferring(last.category === "inference" && last.type === "start");

    const best = scanRecentActivity(events);
    setActivity(best);
  }, [events]);

  // Update speech bubble
  useEffect(() => {
    const text = deriveSpeech(fsmState, activity, inferring);
    setSpeech(text);
    setSpeechVisible(true);
    const timer = setTimeout(() => setSpeechVisible(false), 5000);
    return () => clearTimeout(timer);
  }, [fsmState, activity, inferring]);

  const targetZone = useMemo(
    () => getTargetZone(fsmState, activity),
    [fsmState, activity],
  );
  const zone = scene.zones[targetZone] ?? scene.zones.active;

  return (
    <div
      className="relative bg-[#141414] rounded-2xl overflow-hidden mx-auto mt-8"
      style={{ width: scene.width, height: scene.height }}
      data-testid="pixel-scene"
    >
      {/* Zone markers */}
      {Object.entries(scene.zones).map(([key, z]) => {
        const isTarget = key === targetZone;
        return (
          <div
            key={key}
            className="absolute flex flex-col items-center"
            style={{ left: z.x - 30, top: z.y - 30 }}
          >
            <div
              className={`w-[60px] h-[60px] transition-opacity duration-500 ${isTarget ? "opacity-40" : "opacity-15"}`}
              style={{
                backgroundColor: z.color,
                boxShadow: isTarget ? `0 0 20px ${z.color}40` : "none",
              }}
            />
            <span
              className={`text-xs tracking-wider mt-1 transition-opacity duration-500 ${isTarget ? "opacity-80" : "opacity-40"}`}
              style={{ color: z.color }}
            >
              {z.label}
            </span>
          </div>
        );
      })}

      {/* Character */}
      <div
        className="absolute transition-all duration-1000 ease-in-out"
        style={{
          left: zone.x - scene.character.width / 2,
          top: zone.y - scene.character.height / 2,
          width: scene.character.width,
          height: scene.character.height,
        }}
        data-testid="pixel-character"
        data-zone={targetZone}
      >
        {/* Character sprite */}
        <img
          src={spriteForState(fsmState, inferring, activity)}
          alt="KAIROS"
          className={`w-full h-full object-contain image-rendering-pixelated ${inferring || activity ? "animate-pulse" : ""}`}
          style={{
            filter: inferring || activity ? `drop-shadow(0 0 8px ${zone.color}80)` : "none",
            imageRendering: "pixelated",
          }}
        />

        {/* Speech bubble */}
        {speechVisible && speech && (
          <div
            className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 whitespace-nowrap bg-[#2a2a2a] rounded-lg px-2 py-1 text-xs text-white shadow-lg"
            data-testid="speech-bubble"
          >
            {speech}
          </div>
        )}
      </div>

      {/* Scene label */}
      <div className="absolute bottom-2 right-3 text-xs text-neutral-500 tracking-widest">
        KAIROS // SCENE
      </div>
    </div>
  );
}
