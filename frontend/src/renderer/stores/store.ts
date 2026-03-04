import { create } from "zustand";
import type { Conversation, Message, AppSettings } from "../types";

interface AppState {
  // Conversations
  conversations: Conversation[];
  activeConversationId: string | null;
  setConversations: (conversations: Conversation[]) => void;
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
}

export const useStore = create<AppState>((set) => ({
  // Conversations
  conversations: [],
  activeConversationId: null,
  setConversations: (conversations) => set({ conversations }),
  setActiveConversation: (id) => set({ activeConversationId: id, messages: [] }),
  switchConversation: (id, messages) => set({ activeConversationId: id, messages }),
  addConversation: (conv) =>
    set((s) => ({ conversations: [conv, ...s.conversations] })),
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
}));
