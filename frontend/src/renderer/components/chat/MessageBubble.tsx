import React from "react";
import MarkdownContent from "./MarkdownContent";
import type { Message } from "../../types";

interface Props {
  message: Message;
}

const MessageBubble: React.FC<Props> = ({ message }) => {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end px-4 py-2">
        <div className="max-w-[75%] bg-pastel-purple px-5 py-3 rounded-3xl rounded-br-lg shadow-[0_4px_15px_rgba(5,25,45,0.06)]">
          <p className="whitespace-pre-wrap text-sm leading-relaxed font-semibold text-navy">{message.content}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex px-4 py-2">
      <div className="max-w-[85%] bg-surface px-5 py-3.5 rounded-3xl rounded-bl-lg shadow-[0_4px_15px_rgba(5,25,45,0.04)] border border-warm-200/60">
        <div className="prose prose-warm prose-sm max-w-none text-warm-700">
          <MarkdownContent content={message.content} />
        </div>
      </div>
    </div>
  );
};

export default MessageBubble;
