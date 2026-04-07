import React, { useEffect, useRef } from "react";
import { useChat } from "../../hooks/useChat";
import { useStore } from "../../stores/store";
import MessageBubble from "../chat/MessageBubble";
import StreamingMessage from "../chat/StreamingMessage";

const ChatArea: React.FC = () => {
  const { messages, isStreaming, streamingContent, agentSteps, taskState, pendingAsk, replyToAsk } = useChat();
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
      <div className="flex-1 flex flex-col items-center justify-center pb-[10vh]">
        {/* Animated Orb */}
        <div className="relative w-[220px] h-[220px] flex items-center justify-center mb-12">
          <div
            className="orb-ring-1 absolute w-[240px] h-[240px] bg-pastel-purple opacity-90"
            style={{ top: '50%', left: '50%', transform: 'translate(-45%, -55%)', zIndex: 2 }}
          />
          <div
            className="orb-ring-2 absolute w-[200px] h-[200px] bg-pastel-blue opacity-90"
            style={{ top: '50%', left: '50%', transform: 'translate(-60%, -40%)', zIndex: 1 }}
          />
          <div
            className="orb w-full h-full relative"
            style={{
              background: 'linear-gradient(135deg, var(--color-pastel-pink) 0%, var(--color-surface) 100%)',
              zIndex: 3,
            }}
          />
        </div>

        {/* Hero text */}
        <div className="text-center flex flex-col items-center gap-4">
          <h1 className="text-8xl font-black tracking-tight text-navy leading-none">
            Cape
          </h1>
          <div className="text-base font-bold text-navy bg-surface px-6 py-2.5 rounded-full shadow-[0_8px_25px_rgba(5,25,45,0.05)]">
            Awaiting Input
          </div>
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
            pendingAsk={pendingAsk}
            onReplyToAsk={replyToAsk}
          />
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};

export default ChatArea;
