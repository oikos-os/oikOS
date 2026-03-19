import { useEffect } from "react";
import { IconMenu, IconPlus, IconSearch, IconDashboard, IconScene, IconWorkflow, IconAgents, IconSettings, IconStar, IconStarFilled, IconRooms } from "./icons";

export type Page = "dashboard" | "chat" | "scene" | "search" | "workflows" | "agents" | "rooms" | "settings";

interface ChatSession {
  session_id: string;
  started_at: string;
  first_query?: string;
}

const NAV_ITEMS: { page: Page; label: string; Icon: React.FC<{ className?: string }> }[] = [
  { page: "search", label: "Search", Icon: IconSearch },
  { page: "dashboard", label: "Dashboard", Icon: IconDashboard },
  { page: "scene", label: "Scene", Icon: IconScene },
  { page: "workflows", label: "Workflows", Icon: IconWorkflow },
  { page: "agents", label: "Agents", Icon: IconAgents },
  { page: "rooms", label: "Rooms", Icon: IconRooms },
];

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.floor(hrs / 24)}d`;
}

interface Props {
  page: Page;
  setPage: (p: Page) => void;
  collapsed: boolean;
  onToggle: () => void;
  onNewChat: () => void;
  chats?: ChatSession[];
  starredIds?: Set<string>;
  onOpenSession?: (sessionId: string) => void;
  onToggleStar?: (sessionId: string) => void;
}

export default function Sidebar({ page, setPage, collapsed, onToggle, onNewChat, chats = [], starredIds = new Set(), onOpenSession, onToggleStar }: Props) {
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.ctrlKey && e.shiftKey && e.key === "O") {
        e.preventDefault();
        onNewChat();
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onNewChat]);

  const starred = chats.filter((c) => starredIds.has(c.session_id));
  const recent = chats.filter((c) => !starredIds.has(c.session_id)).slice(0, 15);
  const showLists = !collapsed;

  return (
    <aside
      data-testid="sidebar"
      className={`flex flex-col bg-[var(--bg-tertiary)] border-r border-[var(--border-subtle)] transition-all duration-200 shrink-0 h-screen ${collapsed ? "w-14" : "w-56"}`}
    >
      {/* Top: logo + toggle */}
      <div className="flex items-center h-12 px-3 gap-2">
        <button onClick={onToggle} className="p-1.5 text-neutral-400 hover:text-white" data-testid="sidebar-toggle">
          <IconMenu />
        </button>
        <button
          onClick={onNewChat}
          className={`text-sm font-bold tracking-widest text-white whitespace-nowrap overflow-hidden transition-opacity duration-200 hover:text-amber-400 phosphor-glow ${collapsed ? "opacity-0 w-0" : "opacity-100"}`}
          title="New Chat"
        >
          oikOS
        </button>
      </div>

      {/* New Chat */}
      <button
        onClick={onNewChat}
        className="flex items-center gap-2 mx-2 mb-2 px-2 py-1.5 text-sm text-neutral-300 hover:bg-[#2a2a2a] hover:text-white transition-colors"
        title="New Chat (Ctrl+Shift+O)"
        data-testid="new-chat-btn"
      >
        <IconPlus className="shrink-0" />
        <span className={`whitespace-nowrap overflow-hidden transition-opacity duration-200 ${collapsed ? "opacity-0 w-0" : "opacity-100"}`}>
          New Chat
        </span>
      </button>

      {/* Nav items */}
      <nav className="flex flex-col gap-0.5 px-2">
        {NAV_ITEMS.map(({ page: p, label, Icon }) => (
          <button
            key={p}
            onClick={() => setPage(p)}
            data-testid={`nav-${p}`}
            className={`flex items-center gap-2 px-2 py-1.5 text-sm transition-colors ${
              page === p
                ? "bg-[#2a2a2a] text-white"
                : "text-neutral-500 hover:text-neutral-300"
            }`}
          >
            <Icon className="shrink-0" />
            <span className={`whitespace-nowrap overflow-hidden transition-opacity duration-200 ${collapsed ? "opacity-0 w-0" : "opacity-100"}`}>
              {label}
            </span>
          </button>
        ))}
      </nav>

      {/* Chat history sections */}
      {showLists && (
        <div className="flex-1 flex flex-col min-h-0 mt-3 border-t border-[var(--border-subtle)]">
          <div className="flex-1 overflow-y-auto px-2 py-2">
            {/* Starred */}
            {starred.length > 0 && (
              <div className="mb-3">
                <h4 className="text-[10px] font-bold tracking-widest text-neutral-500 uppercase px-2 mb-1">Starred</h4>
                {starred.map((c) => (
                  <ChatEntry key={c.session_id} chat={c} starred onOpen={onOpenSession} onToggleStar={onToggleStar} />
                ))}
              </div>
            )}

            {/* Recent Chats */}
            {recent.length > 0 && (
              <div>
                <h4 className="text-[10px] font-bold tracking-widest text-neutral-500 uppercase px-2 mb-1">Chats</h4>
                {recent.map((c) => (
                  <ChatEntry key={c.session_id} chat={c} starred={false} onOpen={onOpenSession} onToggleStar={onToggleStar} />
                ))}
                {recent.length >= 15 && (
                  <button
                    onClick={() => setPage("search")}
                    className="w-full text-[10px] text-neutral-500 hover:text-amber-400 py-1.5 transition-colors"
                  >
                    See All
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Settings — pinned bottom */}
      <button
        onClick={() => setPage("settings")}
        data-testid="nav-settings"
        className={`flex items-center gap-2 px-4 py-2.5 text-sm border-t border-[var(--border-subtle)] shrink-0 transition-colors ${
          page === "settings" ? "bg-[#2a2a2a] text-white" : "text-neutral-500 hover:text-neutral-300"
        }`}
      >
        <IconSettings className="shrink-0" />
        <span className={`whitespace-nowrap overflow-hidden transition-opacity duration-200 ${collapsed ? "opacity-0 w-0" : "opacity-100"}`}>
          Settings
        </span>
      </button>
    </aside>
  );
}

function ChatEntry({ chat, starred, onOpen, onToggleStar }: {
  chat: ChatSession;
  starred: boolean;
  onOpen?: (id: string) => void;
  onToggleStar?: (id: string) => void;
}) {
  return (
    <div className="group flex items-center gap-1 px-2 py-1 hover:bg-[#2a2a2a] transition-colors">
      <button
        onClick={() => onOpen?.(chat.session_id)}
        className="flex-1 text-left text-xs text-neutral-400 hover:text-white truncate min-w-0"
        title={chat.first_query || "Untitled"}
      >
        {chat.first_query || "Untitled"}
      </button>
      <span className="text-[10px] text-neutral-600 shrink-0">{timeAgo(chat.started_at)}</span>
      <button
        onClick={(e) => { e.stopPropagation(); onToggleStar?.(chat.session_id); }}
        className={`shrink-0 p-0.5 transition-colors ${starred ? "text-amber-400" : "text-neutral-600 opacity-0 group-hover:opacity-100 hover:text-amber-400"}`}
        title={starred ? "Unstar" : "Star"}
      >
        {starred ? <IconStarFilled className="w-3 h-3" /> : <IconStar className="w-3 h-3" />}
      </button>
    </div>
  );
}
