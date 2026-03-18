import React, { useState, useRef, useEffect } from "react";
import { ArrowUp, Globe } from "lucide-react";
import { useChat } from "../../hooks/useChat";
import { useStore } from "../../stores/store";

const InputBar: React.FC = () => {
  const [input, setInput] = useState("");
  const { sendMessage, isStreaming } = useChat();
  const activeConversationId = useStore((s) => s.activeConversationId);
  const browserPanelVisible = useStore((s) => s.browserPanelVisible);
  const setBrowserPanelVisible = useStore((s) => s.setBrowserPanelVisible);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height =
        Math.min(textareaRef.current.scrollHeight, 200) + "px";
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

  const toggleBrowser = async () => {
    if (browserPanelVisible) {
      try {
        await window.electronAPI.browserPanel.hide();
      } catch { /* ignore */ }
      setBrowserPanelVisible(false);
    } else {
      try {
        await window.electronAPI.browserPanel.show();
      } catch { /* ignore */ }
      setBrowserPanelVisible(true);
    }
  };

  const canSend = input.trim() && !isStreaming && activeConversationId;

  return (
    <div className="px-4 pb-5">
      <div className="bg-white rounded-2xl shadow-sm border border-warm-200 overflow-hidden">
          {/* Textarea area */}
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
            className="w-full px-4 pt-3 pb-2 resize-none outline-none placeholder-warm-400 disabled:opacity-50 bg-transparent text-warm-800 text-sm"
            style={{ minHeight: "80px" }}
          />
          {/* Bottom row: tools area + send button */}
          <div className="flex items-center justify-between px-3 pb-3">
            <div className="flex items-center gap-2">
              <button
                onClick={toggleBrowser}
                className={`p-2 rounded-xl transition-colors ${
                  browserPanelVisible
                    ? "bg-accent-500 text-white"
                    : "text-warm-400 hover:text-warm-600 hover:bg-warm-200 disabled:opacity-50"
                }`}
                title={browserPanelVisible ? "Hide browser" : "Open browser"}
              >
                <Globe size={16} />
              </button>
            </div>
            <button
              onClick={handleSubmit}
              disabled={!canSend}
              className="p-2 bg-accent-500 hover:bg-accent-600 disabled:bg-warm-300 disabled:text-warm-400 text-white rounded-xl transition-colors"
            >
              <ArrowUp size={16} />
            </button>
          </div>
        </div>
    </div>
  );
};

export default InputBar;
