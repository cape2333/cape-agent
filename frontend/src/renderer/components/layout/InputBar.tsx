import React, { useState, useRef, useEffect } from "react";
import { ArrowUp } from "lucide-react";
import { useChat } from "../../hooks/useChat";
import { useStore } from "../../stores/store";

const InputBar: React.FC = () => {
  const [input, setInput] = useState("");
  const { sendMessage, isStreaming } = useChat();
  const activeConversationId = useStore((s) => s.activeConversationId);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height =
        Math.min(textareaRef.current.scrollHeight, 120) + "px";
      textareaRef.current.style.overflowY =
        textareaRef.current.scrollHeight > 120 ? "auto" : "hidden";
    }
  }, [input]);

  const handleSubmit = () => {
    if (!input.trim() || isStreaming || !activeConversationId) return;
    sendMessage(input);
    setInput("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const canSend = input.trim() && !isStreaming && activeConversationId;

  return (
    <div className="px-4 pb-8">
      <div className="max-w-[720px] mx-auto">
        <div className="input-focus-lift bg-surface rounded-[40px] pl-7 pr-3 py-3 flex items-end shadow-[0_15px_45px_rgba(5,25,45,0.08)]">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              activeConversationId
                ? "Type a message..."
                : "Select a conversation first"
            }
            disabled={!activeConversationId || isStreaming}
            rows={1}
            className="flex-1 border-none bg-transparent py-3 text-base font-semibold text-warm-600 resize-none outline-none mr-4 placeholder-warm-300"
            style={{ minHeight: "24px", maxHeight: "120px", lineHeight: 1.5 }}
          />
          <div className="flex items-center gap-2.5 pb-1">
            <button
              onClick={handleSubmit}
              disabled={!canSend}
              className={`w-11 h-11 rounded-full flex items-center justify-center transition-all ${
                canSend
                  ? "bg-pastel-purple text-navy hover:brightness-95 hover:scale-105 cursor-pointer"
                  : "bg-warm-300 text-warm-400 cursor-not-allowed"
              }`}
            >
              <ArrowUp size={18} strokeWidth={2} />
            </button>
          </div>
        </div>
        <p className="text-center text-[12px] font-semibold text-navy-light mt-5">
          Cape Agent may produce inaccurate responses. Verify critical data.
        </p>
      </div>
    </div>
  );
};

export default InputBar;
