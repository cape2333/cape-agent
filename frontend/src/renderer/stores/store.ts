import { create } from "zustand";
import type { Conversation, Message, AppSettings, AgentStep } from "../types";

interface AppState {
  // Conversations
  conversations: Conversation[];
  activeConversationId: string | null;
  setConversations: (conversations: Conversation[]) => void;
  upsertConversation: (conversation: Conversation) => void;
  setActiveConversation: (id: string | null) => void;
  switchConversation: (id: string, messages: Message[]) => void;
  addConversation: (conv: Conversation) => void;
  removeConversation: (id: string) => void;

  // Messages
  messages: Message[];
  setMessages: (messages: Message[]) => void;
  addMessage: (message: Message) => void;

  // Streaming (per-conversation)
  streamingStates: Record<string, { isStreaming: boolean; content: string }>;
  startStreaming: (conversationId: string) => void;
  appendStreamChunk: (conversationId: string, chunk: string) => void;
  finalizeStream: (conversationId: string, fullContent: string) => void;

  // Sidebar
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;

  // Settings
  settings: AppSettings;
  setSettings: (settings: AppSettings) => void;
  showSettings: boolean;
  setShowSettings: (show: boolean) => void;

  // Browser panel
  browserPanelVisible: boolean;
  browserCurrentUrl: string;
  cdpTargetUrl: string | null;
  browserPanelRatio: number;
  setBrowserPanelVisible: (visible: boolean) => void;
  setBrowserCurrentUrl: (url: string) => void;
  setCdpTargetUrl: (url: string | null) => void;
  setBrowserPanelRatio: (ratio: number) => void;

  // Agent steps (per-conversation)
  agentSteps: Record<string, AgentStep[]>;
  addAgentStep: (conversationId: string, step: AgentStep) => void;
  updateAgentStep: (conversationId: string, stepId: string, update: Partial<AgentStep>) => void;
  clearAgentSteps: (conversationId: string) => void;
}

function sortConversations(conversations: Conversation[]): Conversation[] {
  return [...conversations].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

export const useStore = create<AppState>((set) => ({
  // Conversations
  conversations: [],
  activeConversationId: null,
  setConversations: (conversations) => set({ conversations: sortConversations(conversations) }),
  upsertConversation: (conversation) =>
    set((s) => {
      const withoutCurrent = s.conversations.filter((c) => c.id !== conversation.id);
      return {
        conversations: sortConversations([conversation, ...withoutCurrent]),
      };
    }),
  setActiveConversation: (id) => set({ activeConversationId: id, messages: [] }),
  switchConversation: (id, messages) => set({ activeConversationId: id, messages }),
  addConversation: (conv) =>
    set((s) => ({ conversations: sortConversations([conv, ...s.conversations]) })),
  removeConversation: (id) =>
    set((s) => ({
      conversations: s.conversations.filter((c) => c.id !== id),
      activeConversationId: s.activeConversationId === id ? null : s.activeConversationId,
    })),

  // Messages
  messages: [],
  setMessages: (messages) => set({ messages }),
  addMessage: (message) => set((s) => ({ messages: [...s.messages, message] })),

  // Streaming (per-conversation)
  streamingStates: {},
  startStreaming: (conversationId) =>
    set((s) => ({
      streamingStates: {
        ...s.streamingStates,
        [conversationId]: { isStreaming: true, content: "" },
      },
    })),
  appendStreamChunk: (conversationId, chunk) =>
    set((s) => {
      const current = s.streamingStates[conversationId];
      if (!current) return {};
      return {
        streamingStates: {
          ...s.streamingStates,
          [conversationId]: { ...current, content: current.content + chunk },
        },
      };
    }),
  finalizeStream: (conversationId, fullContent) =>
    set((s) => {
      const { [conversationId]: _, ...rest } = s.streamingStates;
      const isActive = s.activeConversationId === conversationId;
      return {
        streamingStates: rest,
        ...(isActive
          ? {
              messages: [
                ...s.messages,
                {
                  id: `msg-${Date.now()}`,
                  conversation_id: conversationId,
                  role: "assistant" as const,
                  content: fullContent,
                  created_at: new Date().toISOString(),
                },
              ],
            }
          : {}),
      };
    }),

  // Sidebar
  sidebarCollapsed: false,
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),

  // Settings
  settings: {
    providers: [{ provider: "openai", model: "gpt-4o-mini", api_key: "" }],
    active_provider_index: 0,
    theme: "system",
  },
  setSettings: (settings) => set({ settings }),
  showSettings: false,
  setShowSettings: (show) => set({ showSettings: show }),

  // Browser panel
  browserPanelVisible: false,
  browserCurrentUrl: "",
  cdpTargetUrl: null,
  browserPanelRatio: 0.5,
  setBrowserPanelVisible: (visible) => set({ browserPanelVisible: visible }),
  setBrowserCurrentUrl: (url) => set({ browserCurrentUrl: url }),
  setCdpTargetUrl: (url) => set({ cdpTargetUrl: url }),
  setBrowserPanelRatio: (ratio) => set({ browserPanelRatio: ratio }),

  // Agent steps
  agentSteps: {},
  addAgentStep: (conversationId, step) =>
    set((s) => ({
      agentSteps: {
        ...s.agentSteps,
        [conversationId]: [...(s.agentSteps[conversationId] || []), step],
      },
    })),
  updateAgentStep: (conversationId, stepId, update) =>
    set((s) => {
      const steps = s.agentSteps[conversationId] || [];
      return {
        agentSteps: {
          ...s.agentSteps,
          [conversationId]: steps.map((step) =>
            step.id === stepId ? { ...step, ...update } : step
          ),
        },
      };
    }),
  clearAgentSteps: (conversationId) =>
    set((s) => ({
      agentSteps: {
        ...s.agentSteps,
        [conversationId]: [],
      },
    })),
}));
