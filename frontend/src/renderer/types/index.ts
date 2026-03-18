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

// Agent step represents one tool call cycle
export interface AgentStep {
  id: string;
  toolName: string;
  toolArgs: Record<string, unknown>;
  result?: string;
  status: "running" | "done" | "error";
  timestamp: string;
}

export interface SSEEvent {
  type: "delta" | "done" | "error" | "tool_start" | "tool_result";
  content: string;
  conversation?: Conversation;
  // For tool_start
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  // For tool_result
  tool_result?: string;
  step_id?: string;
}

export interface BrowserPanelInfo {
  visible: boolean;
  currentUrl: string;
  cdpPort: number;
}

export interface BrowserPanelCreateResult {
  success: boolean;
  cdpTargetUrl?: string;
}

declare global {
  interface Window {
    electronAPI: {
      getBackendUrl: () => Promise<string>;
      browserPanel: {
        create: () => Promise<BrowserPanelCreateResult>;
        show: (sidebarWidth?: number, browserPanelRatio?: number) => Promise<{ success: boolean }>;
        hide: () => Promise<{ success: boolean }>;
        navigate: (url: string) => Promise<{ success: boolean }>;
        resize: (sidebarWidth?: number, browserPanelRatio?: number) => Promise<{ success: boolean }>;
        getInfo: () => Promise<BrowserPanelInfo>;
        destroy: () => Promise<{ success: boolean }>;
      };
    };
  }
}
