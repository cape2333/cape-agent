import React, { useState } from "react";
import MarkdownContent from "./MarkdownContent";
import { Loader2, CheckCircle, XCircle, Globe, Brain, ChevronDown, ChevronRight, User, Bot } from "lucide-react";
import type { AgentStep, AgentLog, TaskStateInfo } from "../../types";
import TaskProgress from "./TaskProgress";

interface Props {
  content: string;
  agentSteps?: AgentStep[];
  taskState?: TaskStateInfo | null;
}

const AgentStepItem: React.FC<{ step: AgentStep }> = ({ step }) => {
  const isRunning = step.status === "running";
  const [expanded, setExpanded] = useState(false);

  const hasArgs = step.toolArgs && Object.keys(step.toolArgs).length > 0;
  const argsSummary = hasArgs
    ? Object.entries(step.toolArgs).map(([k, v]) =>
        `${k}: ${typeof v === 'string' ? v.slice(0, 50) : JSON.stringify(v).slice(0, 50)}`
      ).join(", ")
    : "";

  return (
    <div className="py-1 text-xs">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-start gap-2 w-full text-left"
      >
        <div className="flex-shrink-0 mt-0.5">
          {isRunning ? (
            <Loader2 size={11} className="text-accent-500 animate-spin" />
          ) : (
            <CheckCircle size={11} className="text-green-500" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <span className="font-medium text-warm-600">
            <Globe size={10} className="inline mr-1" />
            {step.toolName}
          </span>
          {hasArgs && !expanded && (
            <span className="text-warm-400 ml-1 truncate inline-block max-w-[300px] align-bottom">
              ({argsSummary})
            </span>
          )}
          {!expanded && step.result && (
            <div className="text-warm-400 mt-0.5 truncate">{step.result}</div>
          )}
        </div>
        <span className="flex-shrink-0 mt-0.5 text-warm-400">
          {expanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
        </span>
      </button>
      {expanded && (
        <div className="ml-6 mt-1 space-y-1">
          {hasArgs && (
            <div className="bg-warm-50 rounded p-2 text-warm-500 whitespace-pre-wrap break-all max-h-60 overflow-y-auto">
              {Object.entries(step.toolArgs).map(([k, v]) => (
                <div key={k}>
                  <span className="font-medium text-warm-600">{k}:</span>{" "}
                  {typeof v === 'string' ? v : JSON.stringify(v, null, 2)}
                </div>
              ))}
            </div>
          )}
          {step.result && (
            <div className="bg-warm-50 rounded p-2 text-warm-500 whitespace-pre-wrap break-all max-h-60 overflow-y-auto">
              <span className="font-medium text-warm-600">Result:</span> {step.result}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const AgentLogItem: React.FC<{ log: AgentLog; steps: AgentStep[] }> = ({ log, steps }) => {
  const [expanded, setExpanded] = useState(log.status === 'running');
  const [outputExpanded, setOutputExpanded] = useState(false);
  const agentSteps = steps.filter(s => s.agentName === log.agentName);
  const isRunning = log.status === 'running';
  const isError = log.status === 'error';

  return (
    <div className="py-1.5">
      {/* Agent header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 w-full text-left group"
      >
        <div className="flex-shrink-0">
          {isRunning ? (
            <Loader2 size={13} className="text-accent-500 animate-spin" />
          ) : isError ? (
            <XCircle size={13} className="text-red-500" />
          ) : (
            <CheckCircle size={13} className="text-green-500" />
          )}
        </div>
        <span className="flex-shrink-0">
          {expanded ? <ChevronDown size={12} className="text-warm-400" /> : <ChevronRight size={12} className="text-warm-400" />}
        </span>
        <Bot size={12} className="text-accent-500 flex-shrink-0" />
        <span className="text-xs font-semibold text-warm-700">{log.agentName}</span>
        {agentSteps.length > 0 && (
          <span className="text-[10px] text-warm-400 ml-1">
            {agentSteps.filter(s => s.status === 'done').length}/{agentSteps.length} tools
          </span>
        )}
      </button>

      {expanded && (
        <div className="ml-6 mt-1 space-y-1">
          {/* Input message */}
          {log.inputMessage && (
            <div className="flex items-start gap-1.5 text-xs">
              <User size={10} className="text-warm-400 mt-0.5 flex-shrink-0" />
              <span className="text-warm-500 line-clamp-2">{log.inputMessage}</span>
            </div>
          )}

          {/* Nested tool calls */}
          {agentSteps.length > 0 && (
            <div className="border-l-2 border-warm-100 pl-2 mt-1">
              {agentSteps.map(step => (
                <AgentStepItem key={step.id} step={step} />
              ))}
            </div>
          )}

          {/* Output message */}
          {log.outputMessage && log.status !== 'running' && (
            <div className="mt-1">
              <button
                onClick={(e) => { e.stopPropagation(); setOutputExpanded(!outputExpanded); }}
                className="flex items-center gap-1 text-xs text-accent-600 hover:text-accent-700"
              >
                {outputExpanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
                <span className="font-medium">{isError ? 'Error' : 'Output'}</span>
              </button>
              {outputExpanded && (
                <div className={`text-xs mt-1 p-2 rounded-md whitespace-pre-wrap break-words max-h-48 overflow-y-auto ${
                  isError ? 'bg-red-50 text-red-700' : 'bg-warm-50 text-warm-600'
                }`}>
                  {log.outputMessage}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const StreamingMessage: React.FC<Props> = ({ content, agentSteps, taskState }) => {
  const hasSteps = agentSteps && agentSteps.length > 0;
  const isWorkforceMode = taskState && taskState.status !== "idle";
  const isDecomposing = taskState?.status === "decomposing";
  const agentLogs = taskState?.agentLogs || [];
  const hasAgentLogs = agentLogs.length > 0;

  // Steps not attributed to any agent log (single-agent mode)
  const unattributedSteps = hasSteps
    ? agentSteps!.filter(s => !s.agentName || !agentLogs.some(l => l.agentName === s.agentName))
    : [];

  if (!content && !hasSteps && !isWorkforceMode) {
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

        {/* Decomposition streaming text */}
        {isDecomposing && taskState.streamingDecomposeText && (
          <div className="mb-2 pb-2 border-b border-warm-100">
            <div className="flex items-center gap-1.5 mb-1">
              <Brain size={12} className="text-accent-500" />
              <span className="text-xs font-medium text-warm-500">Decomposing task...</span>
            </div>
            <div className="text-xs text-warm-400 whitespace-pre-wrap">
              {taskState.streamingDecomposeText}
            </div>
          </div>
        )}

        {/* Task progress (subtasks) */}
        {isWorkforceMode && taskState.subTasks.length > 0 && (
          <div className="mb-2 pb-2 border-b border-warm-100">
            <TaskProgress subTasks={taskState.subTasks} />
          </div>
        )}

        {/* Agent activity timeline (workforce mode) */}
        {hasAgentLogs && (
          <div className="mb-2 pb-2 border-b border-warm-100">
            <div className="divide-y divide-warm-50">
              {agentLogs.map((log) => (
                <AgentLogItem
                  key={`${log.agentId}-${log.timestamp}`}
                  log={log}
                  steps={agentSteps || []}
                />
              ))}
            </div>
          </div>
        )}

        {/* Unattributed agent steps (single-agent / non-workforce tool calls) */}
        {unattributedSteps.length > 0 && (
          <div className="mb-2 pb-2 border-b border-warm-100">
            {unattributedSteps.map((step) => (
              <AgentStepItem key={step.id} step={step} />
            ))}
          </div>
        )}

        {/* Text content */}
        {content && (
          <div className="prose prose-warm prose-sm max-w-none text-warm-700">
            <MarkdownContent content={content} />
            <span className="inline-block w-1.5 h-4 bg-accent-500 animate-pulse ml-0.5 align-text-bottom rounded-sm" />
          </div>
        )}

        {/* Loading states */}
        {!content && !hasSteps && !hasAgentLogs && isWorkforceMode && (
          <div className="flex items-center gap-2">
            <Loader2 size={14} className="text-accent-500 animate-spin" />
            <span className="text-sm text-warm-400">
              {isDecomposing ? "Decomposing task..." : "Agents working..."}
            </span>
          </div>
        )}
        {!content && hasSteps && !isWorkforceMode && !hasAgentLogs && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-warm-400 animate-shimmer">Working...</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default StreamingMessage;
