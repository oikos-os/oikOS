import { useState, useCallback, useEffect } from "react";
import Header from "./components/Header";
import SystemPanel from "./components/SystemPanel";
import CreditsPanel from "./components/CreditsPanel";
import VaultPanel from "./components/VaultPanel";
import AgentPanel from "./components/AgentPanel";
import ActivityFeed from "./components/ActivityFeed";
import ChatView from "./components/ChatView";
import PixelScene from "./components/PixelScene";
import CharacterSheet from "./components/CharacterSheet";
import ToastContainer from "./components/ToastContainer";
import Sidebar from "./components/Sidebar";
import NewChatLanding from "./components/NewChatLanding";
import StubPage from "./components/StubPage";
import SearchPage from "./components/SearchPage";
import SettingsPage from "./components/SettingsPage";
import { useMediaQuery } from "./hooks/useMediaQuery";
import type { Page } from "./components/Sidebar";
import { useApi } from "./hooks/useApi";
import { useChat } from "./hooks/useChat";
import { useHeartbeat } from "./hooks/useHeartbeat";
import { useNotifications } from "./hooks/useNotifications";
import type {
  SystemState,
  HealthStatus,
  CreditBalance,
  SystemConfig,
  VaultStats,
  AgentEvalLatest,
  AgentGauntletLatest,
  EventRecord,
} from "./types";

const POLL_INTERVAL = 30_000;

function loadCollapsed(): boolean {
  try { return localStorage.getItem("sidebar-collapsed") === "true"; } catch { return false; }
}

function loadTheme(): string {
  try { return localStorage.getItem("theme") || "dark"; } catch { return "dark"; }
}

export default function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const [collapsed, setCollapsed] = useState(loadCollapsed);
  const [theme, setTheme] = useState(loadTheme);
  const isMobile = useMediaQuery("(max-width: 768px)");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarChats, setSidebarChats] = useState<{ session_id: string; started_at: string; first_query?: string }[]>([]);
  const [starredIds, setStarredIds] = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(localStorage.getItem("starred-chats") || "[]")); } catch { return new Set(); }
  });

  useEffect(() => {
    fetch("/api/chat/history?limit=30")
      .then((r) => (r.ok ? r.json() : []))
      .then(setSidebarChats)
      .catch(() => {});
  }, []);

  const handleToggleStar = useCallback((id: string) => {
    setStarredIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      try { localStorage.setItem("starred-chats", JSON.stringify([...next])); } catch {}
      return next;
    });
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("theme", theme); } catch {}
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((t) => t === "dark" ? "light" : "dark");
  }, []);

  // Send beacon on tab close for session close
  useEffect(() => {
    function handleUnload() {
      navigator.sendBeacon("/api/session/close", "");
    }
    window.addEventListener("beforeunload", handleUnload);
    return () => window.removeEventListener("beforeunload", handleUnload);
  }, []);
  const { payload: heartbeat, connected } = useHeartbeat();
  const { data: state } = useApi<SystemState>("/api/state", POLL_INTERVAL);
  const { data: health } = useApi<HealthStatus>("/api/health", POLL_INTERVAL);
  const { data: credits } = useApi<CreditBalance>("/api/credits", POLL_INTERVAL);
  const { data: config } = useApi<SystemConfig>("/api/config");
  const { data: vault } = useApi<VaultStats>("/api/vault/stats", POLL_INTERVAL);
  const { data: proposals } = useApi<unknown[]>("/api/agents/consolidation/proposals", POLL_INTERVAL);
  const { data: evalLatest } = useApi<AgentEvalLatest>("/api/agents/eval/latest", POLL_INTERVAL);
  const { data: gauntletLatest } = useApi<AgentGauntletLatest>("/api/agents/gauntlet/latest", POLL_INTERVAL);
  const { data: events } = useApi<EventRecord[]>("/api/events?limit=50", 3_000);
  const chatState = useChat();
  const { toasts, dismiss } = useNotifications(events);

  const handleToggle = useCallback(() => {
    if (isMobile) {
      setSidebarOpen((o) => !o);
    } else {
      setCollapsed((c) => {
        const next = !c;
        try { localStorage.setItem("sidebar-collapsed", String(next)); } catch {}
        return next;
      });
    }
  }, [isMobile]);

  const handleNewChat = useCallback(() => {
    chatState.clear();
    setPage("chat");
    setSidebarOpen(false);
  }, [chatState]);

  const handleOpenSession = useCallback(async (sessionId: string) => {
    try {
      const res = await fetch(`/api/chat/session/${sessionId}`);
      if (!res.ok) return;
      const entries = await res.json();
      const msgs: import("./types").ChatMessage[] = [];
      for (const e of entries) {
        if (e.type === "query") {
          msgs.push({ role: "user", content: e.query });
        } else if (e.type === "response") {
          msgs.push({
            role: "assistant",
            content: e.response_text || e.response_preview || "[no response]",
            confidence: e.confidence,
            route: e.route,
            model: e.model_used,
          });
        }
      }
      chatState.setMessages(msgs);
      setPage("chat");
      setSidebarOpen(false);
    } catch { /* ignore */ }
  }, [chatState]);

  const handleSetPage = useCallback((p: Page) => {
    setPage(p);
    setSidebarOpen(false);
  }, []);

  return (
    <div className="h-screen bg-[var(--bg-primary)] text-[var(--text-primary)] flex overflow-hidden">
      {/* Mobile overlay backdrop */}
      {isMobile && sidebarOpen && (
        <div className="fixed inset-0 bg-black/50 z-30" onClick={() => setSidebarOpen(false)} />
      )}

      {/* Sidebar: overlay on mobile, inline on desktop */}
      {(!isMobile || sidebarOpen) && (
        <div className={isMobile ? "fixed inset-y-0 left-0 z-40" : ""}>
          <Sidebar page={page} setPage={handleSetPage} collapsed={isMobile ? false : collapsed} onToggle={handleToggle} onNewChat={handleNewChat} chats={sidebarChats} starredIds={starredIds} onOpenSession={handleOpenSession} onToggleStar={handleToggleStar} />
        </div>
      )}

      <div className="flex-1 flex flex-col h-screen min-w-0 overflow-hidden">
        <Header state={state} wsConnected={connected} activeModel={chatState.activeModel} onThemeToggle={toggleTheme} theme={theme} />
        <ToastContainer toasts={toasts} onDismiss={dismiss} />

        {/* Mobile hamburger */}
        {isMobile && !sidebarOpen && (
          <button
            onClick={() => setSidebarOpen(true)}
            className="fixed top-2 left-2 z-20 p-2 text-neutral-400 hover:text-white bg-[var(--bg-secondary)] rounded"
            data-testid="mobile-menu"
          >
            <svg viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <path d="M3 5h14M3 10h14M3 15h14" />
            </svg>
          </button>
        )}

        {page === "dashboard" && (
          <main className="flex-1 overflow-y-auto grid grid-cols-1 md:grid-cols-4 grid-rows-[auto_1fr] gap-3 p-4">
            <SystemPanel health={health} heartbeat={heartbeat} />
            <CreditsPanel credits={credits} config={config} />
            <VaultPanel stats={vault} />
            <AgentPanel
              proposals={proposals}
              evalLatest={evalLatest}
              gauntletLatest={gauntletLatest}
            />
            <div className="col-span-1 md:col-span-3 flex flex-col min-h-0">
              <ActivityFeed events={events} />
            </div>
            <CharacterSheet />
          </main>
        )}

        {page === "chat" && chatState.messages.length === 0 && (
          <NewChatLanding onSend={chatState.send} disabled={chatState.streaming} />
        )}

        {page === "chat" && chatState.messages.length > 0 && (
          <ChatView chatState={chatState} />
        )}

        {page === "scene" && <PixelScene heartbeat={heartbeat} events={events} />}
        {page === "search" && <SearchPage onOpenSession={handleOpenSession} />}
        {page === "settings" && <SettingsPage />}
        {page === "workflows" && <StubPage title="WORKFLOW SPACES" />}
        {page === "agents" && <StubPage title="AGENTS" />}
      </div>
    </div>
  );
}
