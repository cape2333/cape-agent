import React, { useEffect, useRef } from "react";
import { useChat } from "../../hooks/useChat";
import { useStore } from "../../stores/store";
import MessageBubble from "../chat/MessageBubble";
import StreamingMessage from "../chat/StreamingMessage";
import { MessageSquare } from "lucide-react";

const ChatArea: React.FC = () => {
  const { messages, isStreaming, streamingContent } = useChat();
  const activeConversationId = useStore((s) => s.activeConversationId);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent]);

  if (!activeConversationId) {
    return (
      <div className="flex-1 flex items-center justify-center text-warm-400">
        <div className="text-center">
          <MessageSquare size={48} className="mx-auto mb-4 opacity-20" />
          <p className="text-lg">Select or create a conversation</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto py-4">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {isStreaming && <StreamingMessage content={streamingContent} />}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};

export default ChatArea;
