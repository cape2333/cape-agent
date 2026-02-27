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
}

export interface ChatRequest {
  conversation_id: string;
  message: string;
  provider?: string;
  model?: string;
  api_key?: string;
  api_base?: string;
}

export interface SSEEvent {
  type: "delta" | "done" | "error";
  content: string;
}

declare global {
  interface Window {
    electronAPI: {
      getBackendUrl: () => Promise<string>;
    };
  }
}
