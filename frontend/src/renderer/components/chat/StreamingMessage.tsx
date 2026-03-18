import React from "react";
import ReactMarkdown from "react-markdown";
import { Loader2, CheckCircle, Globe } from "lucide-react";
import type { AgentStep } from "../../types";

interface Props {
  content: string;
  agentSteps?: AgentStep[];
}

const AgentStepItem: React.FC<{ step: AgentStep }> = ({ step }) => {
  const isRunning = step.status === "running";

  return (
    <div className="flex items-start gap-2 py-1.5 text-xs">
      <div className="flex-shrink-0 mt-0.5">
        {isRunning ? (
          <Loader2 size={12} className="text-accent-500 animate-spin" />
        ) : (
          <CheckCircle size={12} className="text-green-500" />
        )}
      </div>
      <div className="min-w-0">
        <span className="font-medium text-warm-600">
          <Globe size={10} className="inline mr-1" />
          {step.toolName}
        </span>
        {step.toolArgs && Object.keys(step.toolArgs).length > 0 && (
          <span className="text-warm-400 ml-1">
            ({Object.entries(step.toolArgs).map(([k, v]) =>
              `${k}: ${typeof v === 'string' ? v.slice(0, 50) : JSON.stringify(v).slice(0, 50)}`
            ).join(", ")})
          </span>
        )}
        {step.result && (
          <div className="text-warm-400 mt-0.5 truncate">{step.result}</div>
        )}
      </div>
    </div>
  );
};

const StreamingMessage: React.FC<Props> = ({ content, agentSteps }) => {
  const hasSteps = agentSteps && agentSteps.length > 0;

  if (!content && !hasSteps) {
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
        {/* Agent steps */}
        {hasSteps && (
          <div className="mb-2 pb-2 border-b border-warm-100">
            {agentSteps!.map((step) => (
              <AgentStepItem key={step.id} step={step} />
            ))}
          </div>
        )}
        {/* Text content */}
        {content && (
          <div className="prose prose-warm prose-sm max-w-none text-warm-700">
            <ReactMarkdown>{content}</ReactMarkdown>
            <span className="inline-block w-1.5 h-4 bg-accent-500 animate-pulse ml-0.5 align-text-bottom rounded-sm" />
          </div>
        )}
        {!content && hasSteps && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-warm-400 animate-shimmer">Working...</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default StreamingMessage;
