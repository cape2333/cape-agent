import { useCallback, useEffect } from "react";
import { useStore } from "../stores/store";
import * as api from "../services/api";

export function useConversations() {
  const {
    conversations,
    activeConversationId,
    setConversations,
    setActiveConversation,
    addConversation,
    removeConversation,
    setMessages,
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
      setActiveConversation(id);
      const msgs = await api.fetchMessages(id);
      setMessages(msgs);
    },
    [setActiveConversation, setMessages]
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
