import { render, screen, fireEvent } from "@testing-library/react";
import { expect, test, vi, beforeEach } from "vitest";
import App from "./App";
import Header from "./components/Header";
import SystemPanel from "./components/SystemPanel";
import CreditsPanel from "./components/CreditsPanel";
import VaultPanel from "./components/VaultPanel";
import AgentPanel from "./components/AgentPanel";
import ActivityFeed from "./components/ActivityFeed";
import MessageList from "./components/MessageList";
import ConfidenceBadge from "./components/ConfidenceBadge";
import PipelineTrace from "./components/PipelineTrace";
import PixelScene from "./components/PixelScene";
import ToastContainer from "./components/ToastContainer";
import CharacterSheet from "./components/CharacterSheet";
import StubPage from "./components/StubPage";
import { getTargetZone, DEFAULT_SCENE } from "./scene/config";
import type { Toast } from "./hooks/useNotifications";

// Stub fetch, WebSocket, and matchMedia globally
beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
  ));
  vi.stubGlobal("WebSocket", vi.fn(() => ({
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    close: vi.fn(),
  })));
  vi.stubGlobal("matchMedia", vi.fn((q: string) => ({
    matches: false, media: q, onchange: null,
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
  })));
});

// ── App ──────────────────────────────────────────────────────────────

test("renders sidebar with oikOS branding", () => {
  render(<App />);
  expect(screen.getByTestId("sidebar")).toBeInTheDocument();
  expect(screen.getByText("oikOS")).toBeInTheDocument();
});

test("sidebar renders all nav items", () => {
  render(<App />);
  expect(screen.getByTestId("nav-dashboard")).toBeInTheDocument();
  expect(screen.getByTestId("nav-scene")).toBeInTheDocument();
  expect(screen.getByTestId("nav-search")).toBeInTheDocument();
  expect(screen.getByTestId("nav-workflows")).toBeInTheDocument();
  expect(screen.getByTestId("nav-agents")).toBeInTheDocument();
  expect(screen.getByTestId("nav-settings")).toBeInTheDocument();
});

test("sidebar toggle collapses and expands", () => {
  render(<App />);
  const sidebar = screen.getByTestId("sidebar");
  expect(sidebar.className).toContain("w-56");
  fireEvent.click(screen.getByTestId("sidebar-toggle"));
  expect(sidebar.className).toContain("w-14");
  fireEvent.click(screen.getByTestId("sidebar-toggle"));
  expect(sidebar.className).toContain("w-56");
});

test("App switches to chat view with new chat landing", () => {
  render(<App />);
  fireEvent.click(screen.getByTestId("new-chat-btn"));
  expect(screen.getByTestId("new-chat-landing")).toBeInTheDocument();
  expect(screen.getByTestId("landing-input")).toBeInTheDocument();
});

test("new chat button navigates to chat landing", () => {
  render(<App />);
  fireEvent.click(screen.getByTestId("new-chat-btn"));
  expect(screen.getByTestId("new-chat-landing")).toBeInTheDocument();
});

test("App switches to scene view via sidebar", () => {
  render(<App />);
  fireEvent.click(screen.getByTestId("nav-scene"));
  expect(screen.getByTestId("pixel-scene")).toBeInTheDocument();
});

test("search page renders via sidebar", () => {
  render(<App />);
  fireEvent.click(screen.getByTestId("nav-search"));
  expect(screen.getByTestId("search-page")).toBeInTheDocument();
});

test("settings page renders via sidebar", () => {
  render(<App />);
  fireEvent.click(screen.getByTestId("nav-settings"));
  expect(screen.getByTestId("settings-page")).toBeInTheDocument();
});

test("stub pages render for workflows and agents", () => {
  render(<App />);
  fireEvent.click(screen.getByTestId("nav-workflows"));
  expect(screen.getByTestId("stub-workflow-spaces")).toBeInTheDocument();

  fireEvent.click(screen.getByTestId("nav-agents"));
  expect(screen.getByTestId("stub-agents")).toBeInTheDocument();
});

test("theme toggle exists in header", () => {
  render(<App />);
  expect(screen.getByTestId("theme-toggle")).toBeInTheDocument();
});

// ── StubPage ────────────────────────────────────────────────────────

test("StubPage renders title and subtitle", () => {
  render(<StubPage title="TEST" subtitle="Test subtitle" />);
  expect(screen.getByText("TEST")).toBeInTheDocument();
  expect(screen.getByText("Test subtitle")).toBeInTheDocument();
});

// ── Header ───────────────────────────────────────────────────────────

test("Header shows FSM state badge", () => {
  render(
    <Header
      state={{ fsm_state: "active", model: "qwen2.5:14b", version: "0.9.0", uptime: 3661, last_transition: null }}
      wsConnected={true}
    />,
  );
  expect(screen.getByText("active")).toBeInTheDocument();
  expect(screen.getByText("UP 1h 1m")).toBeInTheDocument();
});

test("Header shows disconnected indicator when WS down", () => {
  const { container } = render(
    <Header state={null} wsConnected={false} />,
  );
  const dot = container.querySelector("[title='WebSocket disconnected']");
  expect(dot).toBeInTheDocument();
});

// ── SystemPanel ──────────────────────────────────────────────────────

test("SystemPanel shows VRAM and daemon status", () => {
  render(
    <SystemPanel
      health={{ running: true, daemon: { running: true, vram_used_mb: 4000, vram_total_mb: 12000, ollama_reachable: true }, ollama_embed: true }}
      heartbeat={null}
    />,
  );
  expect(screen.getByText("4000 / 12000 MB")).toBeInTheDocument();
  expect(screen.getByText("ONLINE")).toBeInTheDocument();
  expect(screen.getByText("RUNNING")).toBeInTheDocument();
});

// ── CreditsPanel ─────────────────────────────────────────────────────

test("CreditsPanel shows usage and posture", () => {
  render(
    <CreditsPanel
      credits={{ monthly_cap: 1000000, used_this_month: 250, remaining: 999750, last_reset: "2026-03-01" }}
      config={{ version: "0.9.0", inference_model: "qwen2.5:14b", cloud_model: "gemini-2.5-pro", token_budget: 2000, monthly_cap: 1000000, confidence_threshold: 0.5, cloud_posture: "conservative" }}
    />,
  );
  expect(screen.getByText("250 / 1,000,000")).toBeInTheDocument();
  expect(screen.getByText("conservative")).toBeInTheDocument();
});

// ── VaultPanel ───────────────────────────────────────────────────────

test("VaultPanel renders chunk count", () => {
  render(<VaultPanel stats={{ total_rows: 1234, tier_breakdown: { identity: 50, knowledge: 800 } }} />);
  expect(screen.getByText("1,234")).toBeInTheDocument();
  expect(screen.getByText("identity")).toBeInTheDocument();
});

// ── AgentPanel ───────────────────────────────────────────────────────

test("AgentPanel shows gauntlet score", () => {
  render(
    <AgentPanel
      proposals={[{}, {}]}
      evalLatest={{ avg_score: 0.87 }}
      gauntletLatest={{ total: 10, passed: 10, soft_fails: 0, hard_fails: 0, regressions: 0 }}
    />,
  );
  expect(screen.getByText("2 pending")).toBeInTheDocument();
  expect(screen.getByText("87%")).toBeInTheDocument();
  expect(screen.getByText("10/10")).toBeInTheDocument();
});

// ── ActivityFeed ─────────────────────────────────────────────────────

test("ActivityFeed renders events", () => {
  const events = [
    { timestamp: "2026-03-02T12:00:00Z", category: "fsm", type: "transition", data: {} },
    { timestamp: "2026-03-02T12:01:00Z", category: "inference", type: "start", data: {} },
  ];
  render(<ActivityFeed events={events} />);
  expect(screen.getByText("[fsm]")).toBeInTheDocument();
  expect(screen.getByText("[inference]")).toBeInTheDocument();
  expect(screen.getByText("transition")).toBeInTheDocument();
});

test("ActivityFeed shows empty state", () => {
  render(<ActivityFeed events={[]} />);
  expect(screen.getByText("No events.")).toBeInTheDocument();
});

// ── MessageList ──────────────────────────────────────────────────────

test("MessageList renders user and assistant messages", () => {
  const messages = [
    { role: "user" as const, content: "Hello KAIROS" },
    { role: "assistant" as const, content: "Standing by.", confidence: 75, route: "local", pipeline: { pii: false, adversarial: false, cosine_gate: false, contradiction: false, coherence: true, output_filter: true } },
  ];
  render(<MessageList messages={messages} streaming={false} />);
  expect(screen.getByText("Hello KAIROS")).toBeInTheDocument();
  expect(screen.getByText("Standing by.")).toBeInTheDocument();
  expect(screen.getByText("KAIROS")).toBeInTheDocument();
  expect(screen.getByTestId("pipeline-trace")).toBeInTheDocument();
});

test("MessageList returns null when empty", () => {
  const { container } = render(<MessageList messages={[]} streaming={false} />);
  expect(container.innerHTML).toBe("");
});

test("MessageList renders markdown in responses", () => {
  const messages = [
    { role: "assistant" as const, content: "**bold** and `code`" },
  ];
  const { container } = render(<MessageList messages={messages} streaming={false} />);
  expect(container.querySelector("strong")?.textContent).toBe("bold");
  expect(container.querySelector("code")?.textContent).toBe("code");
});

// ── ConfidenceBadge ──────────────────────────────────────────────────

test("ConfidenceBadge shows HIGH for score >= 60", () => {
  render(<ConfidenceBadge confidence={85} />);
  expect(screen.getByText("HIGH 85")).toBeInTheDocument();
});

test("ConfidenceBadge shows LOW for score < 30", () => {
  render(<ConfidenceBadge confidence={15} />);
  expect(screen.getByText("LOW 15")).toBeInTheDocument();
});

// ── PipelineTrace ────────────────────────────────────────────────────

test("PipelineTrace renders step labels", () => {
  const pipeline = { pii: true, adversarial: false, cosine_gate: true, contradiction: false, coherence: true, output_filter: true };
  render(<PipelineTrace pipeline={pipeline} />);
  expect(screen.getByText("PII")).toBeInTheDocument();
  expect(screen.getByText("COS")).toBeInTheDocument();
  expect(screen.getByText("ADV")).toBeInTheDocument();
});

// ── PixelScene ───────────────────────────────────────────────────────

test("PixelScene renders with zone markers", () => {
  render(<PixelScene heartbeat={null} events={null} />);
  expect(screen.getByTestId("pixel-scene")).toBeInTheDocument();
  expect(screen.getByText("DESK")).toBeInTheDocument();
  expect(screen.getByText("BREAKROOM")).toBeInTheDocument();
  expect(screen.getByText("QUARTERS")).toBeInTheDocument();
  expect(screen.getByText("ARENA")).toBeInTheDocument();
});

test("PixelScene character moves to correct zone on FSM state", () => {
  const { rerender } = render(
    <PixelScene heartbeat={{ fsm_state: "active", daemon: { running: true } }} events={null} />,
  );
  let char = screen.getByTestId("pixel-character");
  expect(char.dataset.zone).toBe("active");

  rerender(
    <PixelScene heartbeat={{ fsm_state: "idle", daemon: { running: true } }} events={null} />,
  );
  char = screen.getByTestId("pixel-character");
  expect(char.dataset.zone).toBe("idle");
});

test("PixelScene shows speech bubble", () => {
  render(
    <PixelScene heartbeat={{ fsm_state: "active", daemon: { running: true } }} events={null} />,
  );
  expect(screen.getByTestId("speech-bubble")).toBeInTheDocument();
});

test("getTargetZone returns activity zone when activity is set", () => {
  expect(getTargetZone("active", "gauntlet")).toBe("gauntlet");
  expect(getTargetZone("idle", "consolidation")).toBe("consolidation");
  expect(getTargetZone("active", null)).toBe("active");
  expect(getTargetZone("asleep", null)).toBe("asleep");
});

test("DEFAULT_SCENE has all required zones", () => {
  const zones = Object.keys(DEFAULT_SCENE.zones);
  expect(zones).toContain("active");
  expect(zones).toContain("idle");
  expect(zones).toContain("asleep");
  expect(zones).toContain("gauntlet");
  expect(zones).toContain("consolidation");
  expect(zones).toContain("error");
});

// ── ToastContainer ───────────────────────────────────────────────────

test("ToastContainer renders critical toast", () => {
  const toasts: Toast[] = [{
    id: "t1", level: "critical", title: "INTERVENTION",
    message: "Escalation triggered", persistent: true, timestamp: Date.now(),
  }];
  render(<ToastContainer toasts={toasts} onDismiss={vi.fn()} />);
  expect(screen.getByTestId("toast-critical")).toBeInTheDocument();
  expect(screen.getByText("INTERVENTION")).toBeInTheDocument();
  expect(screen.getByText("Escalation triggered")).toBeInTheDocument();
});

test("ToastContainer renders warning toast", () => {
  const toasts: Toast[] = [{
    id: "t2", level: "warning", title: "GAUNTLET REGRESSION",
    message: "2 regression(s) detected", persistent: false, timestamp: Date.now(),
  }];
  render(<ToastContainer toasts={toasts} onDismiss={vi.fn()} />);
  expect(screen.getByTestId("toast-warning")).toBeInTheDocument();
  expect(screen.getByText("2 regression(s) detected")).toBeInTheDocument();
});

test("ToastContainer dismiss button calls onDismiss", () => {
  const onDismiss = vi.fn();
  const toasts: Toast[] = [{
    id: "t3", level: "error", title: "ERROR",
    message: "Something failed", persistent: false, timestamp: Date.now(),
  }];
  render(<ToastContainer toasts={toasts} onDismiss={onDismiss} />);
  fireEvent.click(screen.getByText("x"));
  expect(onDismiss).toHaveBeenCalledWith("t3");
});

test("ToastContainer renders nothing when empty", () => {
  const { container } = render(<ToastContainer toasts={[]} onDismiss={vi.fn()} />);
  expect(container.querySelector("[data-testid='toast-container']")).not.toBeInTheDocument();
});

// ── CharacterSheet ───────────────────────────────────────────────────

test("CharacterSheet renders with mock data", async () => {
  const rpgData = {
    level: 5,
    total_xp: 1250,
    xp_progress: 100,
    xp_needed: 500,
    xp_pct: 20,
    stats: { intelligence: 50, defense: 80, memory: 30, constitution: 20, discipline: 45 },
    achievements_unlocked: ["first_blood", "iron_spine"],
    achievements_all: ["first_blood", "iron_spine", "century", "the_face"],
    events_processed: 42,
    counters: {},
  };

  vi.stubGlobal("fetch", vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(rpgData) }),
  ));

  render(<CharacterSheet />);

  const sheet = await screen.findByTestId("character-sheet");
  expect(sheet).toBeInTheDocument();
  expect(screen.getByText("LVL 5")).toBeInTheDocument();
  expect(screen.getByText(/1,250 XP/)).toBeInTheDocument();
  expect(screen.getByText("42 events processed")).toBeInTheDocument();
});

test("CharacterSheet shows unlocked and locked achievements", async () => {
  const rpgData = {
    level: 1,
    total_xp: 0,
    xp_progress: 0,
    xp_needed: 150,
    xp_pct: 0,
    stats: { intelligence: 0, defense: 0, memory: 0, constitution: 0, discipline: 0 },
    achievements_unlocked: ["first_blood"],
    achievements_all: ["first_blood", "century"],
    events_processed: 1,
    counters: {},
  };

  vi.stubGlobal("fetch", vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(rpgData) }),
  ));

  render(<CharacterSheet />);

  await screen.findByTestId("character-sheet");
  const unlocked = screen.getAllByTestId("achievement-unlocked");
  const locked = screen.getAllByTestId("achievement-locked");
  expect(unlocked.length).toBe(1);
  expect(locked.length).toBe(1);
});
