import { useCallback, useEffect, useRef, useState } from "react";
import { IconSearch, IconChevronDown, IconCopy } from "./icons";

interface SearchResult {
  content: string;
  source_path: string;
  score: number | null;
  tier: string | null;
}

interface ChatSession {
  session_id: string;
  started_at: string;
  first_query?: string;
  interaction_count?: number;
  avg_confidence?: number | null;
  duration_minutes?: number;
}

const TIER_COLORS: Record<string, string> = {
  core: "text-red-400",
  semantic: "text-blue-400",
  procedural: "text-green-400",
  episodic: "text-amber-400",
};

function Highlight({ text, query }: { text: string; query: string }) {
  if (!query.trim()) return <>{text}</>;
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parts = text.split(new RegExp(`(${escaped})`, "gi"));
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === query.toLowerCase() ? (
          <mark key={i} className="bg-amber-500/30 text-amber-300 rounded-sm px-0.5">{part}</mark>
        ) : (
          part
        ),
      )}
    </>
  );
}

function VaultResultCard({ result, query }: { result: SearchResult; query: string }) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const isLong = result.content.length > 200;
  const displayContent = expanded || !isLong ? result.content : result.content.slice(0, 200) + "…";

  const copyPath = () => {
    navigator.clipboard.writeText(result.source_path).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="mb-3 bg-[var(--bg-tertiary)] border border-[var(--border-subtle)]">
      <button
        onClick={() => isLong && setExpanded((e) => !e)}
        className={`w-full text-left p-3 ${isLong ? "cursor-pointer hover:border-[var(--accent)]" : "cursor-default"}`}
      >
        <div className="flex items-center gap-2 mb-1">
          {result.tier && (
            <span className={`text-xs font-bold uppercase ${TIER_COLORS[result.tier] || "text-neutral-400"}`}>
              {result.tier}
            </span>
          )}
          {result.score != null && (
            <span className="text-xs text-neutral-500">{result.score}</span>
          )}
          {isLong && (
            <IconChevronDown className={`w-3 h-3 ml-auto text-neutral-500 transition-transform ${expanded ? "rotate-180" : ""}`} />
          )}
        </div>
        <p className="text-sm text-[var(--text-primary)] whitespace-pre-wrap">
          <Highlight text={displayContent} query={query} />
        </p>
      </button>
      <div className="flex items-center justify-between px-3 pb-2">
        <p className="text-xs text-neutral-500 truncate">
          <Highlight text={result.source_path} query={query} />
        </p>
        <button
          onClick={copyPath}
          className="shrink-0 ml-2 text-xs text-neutral-500 hover:text-amber-400 flex items-center gap-1 transition-colors"
          title="Copy path"
        >
          <IconCopy className="w-3 h-3" />
          {copied ? "Copied" : ""}
        </button>
      </div>
    </div>
  );
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

interface Props {
  onOpenSession?: (sessionId: string) => void;
}

export default function SearchPage({ onOpenSession }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [allChats, setAllChats] = useState<ChatSession[]>([]);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const searchAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    fetch("/api/chat/history?limit=20")
      .then((r) => (r.ok ? r.json() : []))
      .then(setAllChats)
      .catch(() => {});
    return () => { clearTimeout(debounceRef.current); searchAbortRef.current?.abort(); };
  }, []);

  const doSearch = useCallback(async (q: string) => {
    searchAbortRef.current?.abort();
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setLoading(true);
    const controller = new AbortController();
    searchAbortRef.current = controller;
    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=20`, { signal: controller.signal });
      if (res.ok) {
        const data = await res.json();
        setResults(data.results || []);
      }
    } catch {
      if (!controller.signal.aborted) setResults([]);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  const handleInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(val), 300);
  }, [doSearch]);

  // Filter chats by query (match against first_query)
  const filteredChats = query.trim()
    ? allChats.filter((c) => c.first_query?.toLowerCase().includes(query.toLowerCase()))
    : allChats;

  const [chatLimit, setChatLimit] = useState(10);
  const visibleChats = filteredChats.slice(0, chatLimit);
  const hasMoreChats = filteredChats.length > chatLimit;
  const hasQuery = query.trim().length > 0;

  return (
    <div className="flex-1 flex flex-col p-4 max-w-4xl mx-auto w-full overflow-y-auto" data-testid="search-page">
      <h2 className="text-lg font-bold tracking-widest mb-4">SEARCH</h2>

      <div className="relative mb-4">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500 pointer-events-none">
          <IconSearch className="w-4 h-4" />
        </span>
        <input
          ref={inputRef}
          type="text"
          placeholder="Search the vault..."
          className="w-full bg-[var(--bg-elevated)] text-[var(--text-primary)] pl-9 pr-3 py-2 text-sm outline-none border border-[var(--border-subtle)] focus:border-[var(--accent)]"
          onChange={handleInput}
          data-testid="search-input"
        />
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Filtered chats */}
        {visibleChats.length > 0 && (
          <>
            <h3 className="text-xs font-bold tracking-widest text-neutral-500 uppercase mb-2">
              {hasQuery ? "Matching Chats" : "Recent Chats"}
            </h3>
            {visibleChats.map((chat) => (
              <button
                key={chat.session_id}
                onClick={() => onOpenSession?.(chat.session_id)}
                className="w-full text-left mb-2 p-3 bg-[var(--bg-tertiary)] border border-[var(--border-subtle)] hover:border-[var(--accent)] transition-colors group"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm text-[var(--text-primary)] group-hover:text-amber-400 transition-colors truncate">
                    {hasQuery ? (
                      <Highlight text={chat.first_query || "Untitled session"} query={query} />
                    ) : (
                      chat.first_query || "Untitled session"
                    )}
                  </span>
                  <span className="text-xs text-neutral-500 shrink-0 ml-2">{timeAgo(chat.started_at)}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-neutral-500">
                  <span>{chat.interaction_count ?? 0} messages</span>
                  {chat.duration_minutes != null && <span>{Math.round(chat.duration_minutes)}m</span>}
                  {chat.avg_confidence != null && <span>{Math.round(chat.avg_confidence)}% avg confidence</span>}
                </div>
              </button>
            ))}
            {hasMoreChats && (
              <button
                onClick={() => setChatLimit((n) => n + 10)}
                className="w-full text-xs text-neutral-500 hover:text-amber-400 py-2 transition-colors"
              >
                See More ({filteredChats.length - chatLimit} remaining)
              </button>
            )}
          </>
        )}

        {/* Vault search results */}
        {hasQuery && (
          <>
            <h3 className="text-xs font-bold tracking-widest text-neutral-500 uppercase mb-2 mt-4">
              Vault Results {loading && <span className="text-amber-400 ml-1">...</span>}
            </h3>
            {results.map((r, i) => (
              <VaultResultCard key={i} result={r} query={query} />
            ))}
            {!loading && results.length === 0 && (
              <p className="text-neutral-500 text-sm">No vault results.</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
