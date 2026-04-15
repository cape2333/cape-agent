export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface ProviderSettings {
  provider: string;
  model: string;
  api_key: string;
  api_base?: string;
}

export interface AppSettings {
  providers: ProviderSettings[];
  active_provider_index: number;
  theme: 'light' | 'dark' | 'system';
}

export interface ChatRequest {
  conversation_id: string;
  message: string;
  provider?: string;
  model?: string;
  api_key?: string;
  api_base?: string;
}

// Multi-agent task tracking
export interface SubTask {
  id: string;
  content: string;
  state: 'open' | 'waiting' | 'running' | 'done' | 'failed';
  assigneeId?: string;
  result?: string;
  dependencies?: string[];
}

export interface AgentActivity {
  agentId: string;
  agentName: string;
  processTaskId: string;
  message: string;
}

export interface AgentLog {
  agentId: string;
  agentName: string;
  processTaskId: string;
  status: 'running' | 'done' | 'error';
  inputMessage: string;
  outputMessage: string;
  timestamp: string;
}

export interface PendingAsk {
  agentName: string;
  question: string;
  timestamp: string;
}

export interface TaskStateInfo {
  status: 'idle' | 'classifying' | 'decomposing' | 'executing' | 'done';
  subTasks: SubTask[];
  activeAgents: AgentActivity[];
  agentLogs: AgentLog[];
  streamingDecomposeText: string;
  pendingAsk?: PendingAsk | null;
}

// Agent step represents one tool call cycle
export interface AgentStep {
  id: string;
  toolName: string;
  toolArgs: Record<string, unknown>;
  result?: string;
  status: "running" | "done" | "error";
  timestamp: string;
  agentName?: string;
}

export interface SSEEvent {
  step: string;
  data: Record<string, unknown>;
}

// --- Skills ---

export interface SkillMeta {
  name: string;
  description: string;
  agent_type: "browser" | "developer" | "document";
  version: number;
  enabled: boolean;
  created_by: "agent" | "user";
  created_at: string;
  updated_at: string;
  tags: string[];
}

export interface SkillDetail extends SkillMeta {
  content: string;
  raw: string;
  files: string[];
}

export interface SkillCreate {
  name: string;
  description: string;
  agent_type: "browser" | "developer" | "document";
  content: string;
  tags: string[];
}

export interface SkillUpdate {
  description?: string;
  content?: string;
  tags?: string[];
  enabled?: boolean;
}

export interface SkillStats {
  name: string;
  loads: number;
  patches: number;
  last_used: string | null;
}

declare global {
  interface Window {
    electronAPI: {
      getBackendUrl: () => Promise<string>;
    };
  }
}
