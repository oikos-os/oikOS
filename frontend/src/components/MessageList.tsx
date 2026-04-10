import { useEffect, useRef } from "react";
import Markdown from "react-markdown";
import type { ChatMessage } from "../types";
import ConfidenceBadge from "./ConfidenceBadge";
import PipelineTrace from "./PipelineTrace";
import ThinkingIndicator from "./ThinkingIndicator";

interface Props {
  messages: ChatMessage[];
  streaming: boolean;
}

export default function MessageList({ messages, streaming }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) return null;

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4" data-testid="message-list">
      {messages.map((msg, i) => (
        <div key={i} className={msg.role === "user" ? "flex justify-end" : ""}>
          <div
            className={
              msg.role === "user"
                ? "max-w-[70%] bg-[var(--bg-elevated)] p-3 text-base text-white"
                : "max-w-[85%] text-base"
            }
          >
            {msg.role === "assistant" && (
              <div className="text-xs text-amber-600 tracking-wider mb-1 flex items-center gap-3">
                <span>KAIROS</span>
                {msg.route && <span className="text-neutral-600">{msg.route}</span>}
                <ConfidenceBadge confidence={msg.confidence} />
                {msg.model && (
                  <span className="text-neutral-500 font-mono" data-testid="model-badge">
                    {msg.auto ? `auto \u2192 ${msg.model}` : msg.model}
                  </span>
                )}
              </div>
            )}

            <div className="prose prose-invert prose-base max-w-none [&_pre]:bg-[var(--bg-tertiary)] [&_pre]:border [&_pre]:border-neutral-700/50 [&_pre]:p-3 [&_code]:text-amber-400 [&_a]:text-amber-500">
              <Markdown>{msg.content}</Markdown>
            </div>

            {msg.role === "assistant" && msg.pipeline && (
              <div className="mt-2">
                <PipelineTrace pipeline={msg.pipeline} piiScrubbed={msg.pii_scrubbed} />
              </div>
            )}

            {msg.role === "assistant" && msg.routing_trace?.badge && (
              <div className="mt-1 text-xs text-neutral-500 font-mono" data-testid="routing-badge">
                {msg.routing_trace.output_filtered && (
                  <span className="text-amber-500">! </span>
                )}
                {msg.routing_trace.badge}
              </div>
            )}

            {msg.role === "assistant" && streaming && i === messages.length - 1 && !msg.pipeline && (
              <ThinkingIndicator />
            )}
          </div>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}
