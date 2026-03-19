import type { useChat } from "../hooks/useChat";
import MessageInput from "./MessageInput";
import MessageList from "./MessageList";

interface Props {
  chatState: ReturnType<typeof useChat>;
}

export default function ChatView({ chatState }: Props) {
  const { messages, streaming, send } = chatState;

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <MessageList messages={messages} streaming={streaming} />
      <MessageInput onSend={send} disabled={streaming} />
    </div>
  );
}
