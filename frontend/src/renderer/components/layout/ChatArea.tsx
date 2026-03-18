import React, { useEffect, useRef } from "react";
import { useChat } from "../../hooks/useChat";
import { useConversations } from "../../hooks/useConversations";
import { useStore } from "../../stores/store";
import MessageBubble from "../chat/MessageBubble";
import StreamingMessage from "../chat/StreamingMessage";
import { Plus } from "lucide-react";
import appIcon from "../../../resources/icon.png";

const ChatArea: React.FC = () => {
  const { messages, isStreaming, streamingContent, agentSteps, taskState } = useChat();
  const { createNew } = useConversations();
  const activeConversationId = useStore((s) => s.activeConversationId);
  const bottomRef = useRef<HTMLDivElement>(null);
  const justSwitchedRef = useRef(false);

  useEffect(() => {
    justSwitchedRef.current = true;
  }, [activeConversationId]);

  useEffect(() => {
    if (messages.length === 0 && !streamingContent) return;
    if (justSwitchedRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "instant" });
      justSwitchedRef.current = false;
    } else {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, streamingContent, agentSteps]);

  if (!activeConversationId) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <img src={appIcon} alt="Cape Agent" className="w-20 h-20 mx-auto mb-6 rounded-2xl" />
          <p className="text-xl font-medium text-warm-700 mb-2">Agent for Cape Long</p>
          <p className="text-sm text-warm-400 mb-8">Your intelligent assistant, ready to help.</p>
          <button
            onClick={createNew}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-accent-500 text-white text-sm font-medium hover:bg-accent-600 transition-colors"
          >
            <Plus size={16} />
            New Chat
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div key={activeConversationId} className="mx-auto py-4 px-4 animate-chat-fade-in">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {isStreaming && (
          <StreamingMessage
            content={streamingContent}
            agentSteps={agentSteps}
            taskState={taskState}
          />
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};

export default ChatArea;
