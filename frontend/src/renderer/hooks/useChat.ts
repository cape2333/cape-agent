import { useCallback } from "react";
import { useStore } from "../stores/store";
import * as api from "../services/api";

export function useChat() {
  const {
    messages,
    isStreaming,
    streamingContent,
    activeConversationId,
    settings,
    addMessage,
    setIsStreaming,
    appendStreamChunk,
    finalizeStream,
  } = useStore();

  const sendMessage = useCallback(
    async (content: string) => {
      if (!activeConversationId || !content.trim() || isStreaming) return;

      const activeProvider = settings.providers[settings.active_provider_index];

      // Add user message to UI immediately
      addMessage({
        id: `msg-${Date.now()}`,
        conversation_id: activeConversationId,
        role: "user",
        content: content.trim(),
        created_at: new Date().toISOString(),
      });

      setIsStreaming(true);

      await api.sendChatMessage(
        {
          conversation_id: activeConversationId,
          message: content.trim(),
          provider: activeProvider?.provider,
          model: activeProvider?.model,
          api_key: activeProvider?.api_key,
          api_base: activeProvider?.api_base,
        },
        (delta) => appendStreamChunk(delta),
        (fullContent) => finalizeStream(fullContent, activeConversationId),
        (error) => {
          console.error("Chat error:", error);
          finalizeStream(`Error: ${error}`, activeConversationId);
        }
      );
    },
    [
      activeConversationId,
      isStreaming,
      settings,
      addMessage,
      setIsStreaming,
      appendStreamChunk,
      finalizeStream,
    ]
  );

  return { messages, isStreaming, streamingContent, sendMessage };
}
