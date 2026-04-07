import React, { useState, useRef, useEffect } from "react";
import { HelpCircle, ArrowUp, Bot } from "lucide-react";
import MarkdownContent from "./MarkdownContent";

interface Props {
  agentName: string;
  question: string;
  onReply: (response: string) => void;
}

const AskBubble: React.FC<Props> = ({ agentName, question, onReply }) => {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height =
        Math.min(textareaRef.current.scrollHeight, 100) + "px";
    }
  }, [input]);

  const handleSubmit = () => {
    if (!input.trim()) return;
    onReply(input.trim());
    setInput("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="space-y-2">
      {/* Header */}
      <div className="flex items-center gap-1.5">
        <HelpCircle size={13} className="text-accent-500" />
        <span className="text-xs font-bold text-navy">
          <Bot size={11} className="inline mr-1" />
          {agentName}
        </span>
        <span className="text-xs text-navy-light">needs your input</span>
      </div>

      {/* Question */}
      <div className="prose prose-warm prose-sm max-w-none text-warm-700">
        <MarkdownContent content={question} />
      </div>

      {/* Reply input */}
      <div className="flex items-end gap-2 bg-warm-50 rounded-2xl pl-4 pr-2 py-2">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type your reply..."
          rows={1}
          className="flex-1 border-none bg-transparent py-1 text-sm font-semibold text-warm-600 resize-none outline-none placeholder-warm-300"
          style={{ minHeight: "20px", maxHeight: "100px", lineHeight: 1.5 }}
        />
        <button
          onClick={handleSubmit}
          disabled={!input.trim()}
          className={`w-8 h-8 rounded-full flex items-center justify-center transition-all flex-shrink-0 ${
            input.trim()
              ? "bg-pastel-purple text-navy hover:brightness-95 hover:scale-105 cursor-pointer"
              : "bg-warm-300 text-warm-400 cursor-not-allowed"
          }`}
        >
          <ArrowUp size={14} strokeWidth={2} />
        </button>
      </div>
    </div>
  );
};

export default AskBubble;
