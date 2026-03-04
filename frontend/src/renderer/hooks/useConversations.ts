import { useCallback, useEffect } from "react";
import { useStore } from "../stores/store";
import * as api from "../services/api";

export function useConversations() {
  const {
    conversations,
    activeConversationId,
    setConversations,
    setActiveConversation,
    switchConversation,
    addConversation,
    removeConversation,
  } = useStore();

  const loadConversations = useCallback(async () => {
    const convs = await api.fetchConversations();
    setConversations(convs);
  }, [setConversations]);

  const createNew = useCallback(async () => {
    const conv = await api.createConversation();
    addConversation(conv);
    setActiveConversation(conv.id);
  }, [addConversation, setActiveConversation]);

  const select = useCallback(
    async (id: string) => {
      if (id === activeConversationId) return;
      const msgs = await api.fetchMessages(id);
      switchConversation(id, msgs);
    },
    [activeConversationId, switchConversation]
  );

  const remove = useCallback(
    async (id: string) => {
      await api.deleteConversation(id);
      removeConversation(id);
    },
    [removeConversation]
  );

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  return { conversations, activeConversationId, createNew, select, remove };
}
