import { useCallback } from "react";
import { useStore } from "../stores/store";
import * as api from "../services/api";

export function useChat() {
  const {
    messages,
    activeConversationId,
    settings,
    addMessage,
    streamingStates,
    startStreaming,
    finalizeStream,
    upsertConversation,
    agentSteps,
    clearAgentSteps,
    handleSSEEvent,
    resetTaskState,
    taskStates,
  } = useStore();

  const streamState = activeConversationId
    ? streamingStates[activeConversationId]
    : undefined;
  const isStreaming = streamState?.isStreaming ?? false;
  const streamingContent = streamState?.content ?? "";

  const currentSteps = activeConversationId
    ? agentSteps[activeConversationId] || []
    : [];

  const currentTaskState = activeConversationId
    ? taskStates[activeConversationId] || null
    : null;

  const sendMessage = useCallback(
    async (content: string) => {
      if (!activeConversationId || !content.trim() || isStreaming) return;

      const conversationId = activeConversationId;
      const activeProvider = settings.providers[settings.active_provider_index];

      addMessage({
        id: `msg-${Date.now()}`,
        conversation_id: conversationId,
        role: "user",
        content: content.trim(),
        created_at: new Date().toISOString(),
      });

      startStreaming(conversationId);
      clearAgentSteps(conversationId);
      resetTaskState(conversationId);

      await api.sendChatMessage(
        {
          conversation_id: conversationId,
          message: content.trim(),
          provider: activeProvider?.provider,
          model: activeProvider?.model,
          api_key: activeProvider?.api_key,
          api_base: activeProvider?.api_base,
        },
        (event) => handleSSEEvent(conversationId, event),
      );
    },
    [
      activeConversationId,
      isStreaming,
      settings,
      addMessage,
      startStreaming,
      clearAgentSteps,
      resetTaskState,
      handleSSEEvent,
    ]
  );

  return {
    messages,
    isStreaming,
    streamingContent,
    sendMessage,
    agentSteps: currentSteps,
    taskState: currentTaskState,
  };
}
