import React from "react";
import ReactMarkdown from "react-markdown";

interface Props {
  content: string;
}

const StreamingMessage: React.FC<Props> = ({ content }) => {
  if (!content) {
    return (
      <div className="flex px-4 py-2">
        <div className="bg-white px-4 py-3 rounded-2xl rounded-bl-md shadow-sm border border-warm-200">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium animate-shimmer">Analyzing your request...</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex px-4 py-2">
      <div className="max-w-[85%] bg-white px-4 py-3 rounded-2xl rounded-bl-md shadow-sm border border-warm-200">
        <div className="prose prose-warm prose-sm max-w-none text-warm-700">
          <ReactMarkdown>{content}</ReactMarkdown>
          <span className="inline-block w-1.5 h-4 bg-accent-500 animate-pulse ml-0.5 align-text-bottom rounded-sm" />
        </div>
      </div>
    </div>
  );
};

export default StreamingMessage;
