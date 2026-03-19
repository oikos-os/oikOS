export interface ZoneConfig {
  x: number;
  y: number;
  label: string;
  color: string;
}

export interface SceneConfig {
  width: number;
  height: number;
  zones: Record<string, ZoneConfig>;
  character: {
    width: number;
    height: number;
    color: string;
  };
}

export const DEFAULT_SCENE: SceneConfig = {
  width: 800,
  height: 500,
  zones: {
    active:        { x: 400, y: 250, label: "DESK",        color: "#D4A017" },
    idle:          { x: 650, y: 80,  label: "BREAKROOM",    color: "#3B82F6" },
    asleep:        { x: 650, y: 400, label: "QUARTERS",     color: "#6366F1" },
    scanning:      { x: 120, y: 80,  label: "SCANNER",      color: "#22D3EE" },
    gauntlet:      { x: 120, y: 400, label: "ARENA",        color: "#EF4444" },
    consolidation: { x: 120, y: 250, label: "FILE ROOM",    color: "#A855F7" },
    eval:          { x: 260, y: 400, label: "EVAL LAB",     color: "#F59E0B" },
    cloud:         { x: 260, y: 80,  label: "CLOUD",        color: "#38BDF8" },
    memory:        { x: 540, y: 250, label: "MEMORY",       color: "#818CF8" },
    error:         { x: 650, y: 250, label: "BUG STATION",  color: "#DC143C" },
  },
  character: {
    width: 32,
    height: 32,
    color: "#D4A017",
  },
};

export type FsmState = "active" | "idle" | "asleep";
export type AgentActivity = "scanning" | "gauntlet" | "consolidation" | "eval" | "cloud" | "memory" | "error" | null;

export function getTargetZone(fsmState: FsmState, activity: AgentActivity): string {
  if (activity) return activity;
  return fsmState;
}
