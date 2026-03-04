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
    appendStreamChunk,
    finalizeStream,
  } = useStore();

  const streamState = activeConversationId
    ? streamingStates[activeConversationId]
    : undefined;
  const isStreaming = streamState?.isStreaming ?? false;
  const streamingContent = streamState?.content ?? "";

  const sendMessage = useCallback(
    async (content: string) => {
      if (!activeConversationId || !content.trim() || isStreaming) return;

      const conversationId = activeConversationId;
      const activeProvider = settings.providers[settings.active_provider_index];

      // Add user message to UI immediately
      addMessage({
        id: `msg-${Date.now()}`,
        conversation_id: conversationId,
        role: "user",
        content: content.trim(),
        created_at: new Date().toISOString(),
      });

      startStreaming(conversationId);

      await api.sendChatMessage(
        {
          conversation_id: conversationId,
          message: content.trim(),
          provider: activeProvider?.provider,
          model: activeProvider?.model,
          api_key: activeProvider?.api_key,
          api_base: activeProvider?.api_base,
        },
        (delta) => appendStreamChunk(conversationId, delta),
        (fullContent) => finalizeStream(conversationId, fullContent),
        (error) => {
          console.error("Chat error:", error);
          finalizeStream(conversationId, `Error: ${error}`);
        }
      );
    },
    [
      activeConversationId,
      isStreaming,
      settings,
      addMessage,
      startStreaming,
      appendStreamChunk,
      finalizeStream,
    ]
  );

  return { messages, isStreaming, streamingContent, sendMessage };
}
