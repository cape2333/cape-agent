import { useCallback } from "react";
import { useStore } from "../stores/store";
import * as api from "../services/api";
import type { AgentStep } from "../types";

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
    upsertConversation,
    agentSteps,
    addAgentStep,
    updateAgentStep,
    clearAgentSteps,
    setBrowserPanelVisible,
    setBrowserCurrentUrl,
  } = useStore();

  const streamState = activeConversationId
    ? streamingStates[activeConversationId]
    : undefined;
  const isStreaming = streamState?.isStreaming ?? false;
  const streamingContent = streamState?.content ?? "";

  const currentSteps = activeConversationId
    ? agentSteps[activeConversationId] || []
    : [];

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
      clearAgentSteps(conversationId);

      await api.sendChatMessage(
        {
          conversation_id: conversationId,
          message: content.trim(),
          provider: activeProvider?.provider,
          model: activeProvider?.model,
          api_key: activeProvider?.api_key,
          api_base: activeProvider?.api_base,
        },
        // onDelta
        (delta) => appendStreamChunk(conversationId, delta),
        // onDone
        (fullContent, conversation) => {
          finalizeStream(conversationId, fullContent);
          if (conversation) {
            upsertConversation(conversation);
          }
        },
        // onError
        (error, conversation) => {
          console.error("Chat error:", error);
          finalizeStream(conversationId, `Error: ${error}`);
          if (conversation) {
            upsertConversation(conversation);
          }
        },
        // onToolStart — also auto-show browser panel when agent uses tools
        (stepId, toolName, toolArgs) => {
          const step: AgentStep = {
            id: stepId,
            toolName,
            toolArgs,
            status: "running",
            timestamp: new Date().toISOString(),
          };
          addAgentStep(conversationId, step);

          // Auto-open browser panel and always re-enforce bounds
          const sw = useStore.getState().sidebarCollapsed ? 0 : 268;
          if (!useStore.getState().browserPanelVisible) {
            setBrowserPanelVisible(true);
            setBrowserCurrentUrl("about:blank");
          }
          // Always call show() to re-enforce bounds (Electron can reset them on navigation)
          window.electronAPI.browserPanel.show(sw);
        },
        // onToolResult
        (stepId, toolName, toolResult) => {
          updateAgentStep(conversationId, stepId, {
            result: toolResult,
            status: "done",
          });
        },
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
      upsertConversation,
      clearAgentSteps,
      addAgentStep,
      updateAgentStep,
      setBrowserPanelVisible,
      setBrowserCurrentUrl,
    ]
  );

  return { messages, isStreaming, streamingContent, sendMessage, agentSteps: currentSteps };
}
