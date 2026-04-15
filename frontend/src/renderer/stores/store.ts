import { create } from "zustand";
import type { Conversation, Message, AppSettings, AgentStep, SSEEvent, TaskStateInfo, SubTask, AgentActivity, AgentLog, PendingAsk, SkillMeta, SkillDetail, SkillStats } from "../types";

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

  // Agent steps (per-conversation)
  agentSteps: Record<string, AgentStep[]>;
  addAgentStep: (conversationId: string, step: AgentStep) => void;
  updateAgentStep: (conversationId: string, stepId: string, update: Partial<AgentStep>) => void;
  clearAgentSteps: (conversationId: string) => void;

  // Task states (per-conversation, for workforce mode)
  taskStates: Record<string, TaskStateInfo>;
  handleSSEEvent: (conversationId: string, event: SSEEvent) => void;
  resetTaskState: (conversationId: string) => void;
  clearPendingAsk: (conversationId: string) => void;

  // Skills
  skills: SkillMeta[];
  activeSkill: SkillDetail | null;
  skillStats: Record<string, SkillStats>;
  setSkills: (skills: SkillMeta[]) => void;
  setActiveSkill: (skill: SkillDetail | null) => void;
  setSkillStats: (stats: SkillStats[]) => void;
  updateSkillInList: (updated: SkillMeta) => void;
  removeSkillFromList: (name: string) => void;

  // Skills UI
  showSkills: boolean;
  setShowSkills: (show: boolean) => void;
  skillsView: { page: "list" | "detail" | "edit" | "new"; name?: string };
  setSkillsView: (view: { page: "list" | "detail" | "edit" | "new"; name?: string }) => void;
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

  // Task states
  taskStates: {},

  resetTaskState: (conversationId) =>
    set((s) => ({
      taskStates: {
        ...s.taskStates,
        [conversationId]: {
          status: 'idle',
          subTasks: [],
          activeAgents: [],
          agentLogs: [],
          streamingDecomposeText: '',
          pendingAsk: null,
        },
      },
    })),

  clearPendingAsk: (conversationId) =>
    set((s) => {
      const ts = s.taskStates[conversationId];
      if (!ts) return {};
      return {
        taskStates: {
          ...s.taskStates,
          [conversationId]: { ...ts, pendingAsk: null },
        },
      };
    }),

  handleSSEEvent: (conversationId, event) =>
    set((s) => {
      const step = event.step;
      const data = event.data as Record<string, any>;

      switch (step) {
        case 'delta': {
          const current = s.streamingStates[conversationId];
          if (!current) return {};
          return {
            streamingStates: {
              ...s.streamingStates,
              [conversationId]: {
                ...current,
                content: current.content + (data.content || ''),
              },
            },
          };
        }

        case 'done': {
          const { [conversationId]: _, ...restStreaming } = s.streamingStates;
          const isActive = s.activeConversationId === conversationId;
          return {
            streamingStates: restStreaming,
            ...(isActive ? {
              messages: [
                ...s.messages,
                {
                  id: `msg-${Date.now()}`,
                  conversation_id: conversationId,
                  role: 'assistant' as const,
                  content: data.content || '',
                  created_at: new Date().toISOString(),
                },
              ],
            } : {}),
            ...(data.conversation ? {
              conversations: sortConversations(
                s.conversations.map(c =>
                  c.id === data.conversation.id ? data.conversation : c
                )
              ),
            } : {}),
            taskStates: {
              ...s.taskStates,
              [conversationId]: {
                ...(s.taskStates[conversationId] || { subTasks: [], activeAgents: [], agentLogs: [], streamingDecomposeText: '' }),
                status: 'done',
              },
            },
          };
        }

        case 'error': {
          const { [conversationId]: _e, ...restStreamingErr } = s.streamingStates;
          const isActiveErr = s.activeConversationId === conversationId;
          return {
            streamingStates: restStreamingErr,
            ...(isActiveErr ? {
              messages: [
                ...s.messages,
                {
                  id: `msg-${Date.now()}`,
                  conversation_id: conversationId,
                  role: 'assistant' as const,
                  content: `Error: ${data.message || 'Unknown error'}`,
                  created_at: new Date().toISOString(),
                },
              ],
            } : {}),
          };
        }

        case 'decompose_text': {
          const ts = s.taskStates[conversationId] || {
            status: 'decomposing', subTasks: [], activeAgents: [], agentLogs: [], streamingDecomposeText: '',
          };
          return {
            taskStates: {
              ...s.taskStates,
              [conversationId]: {
                ...ts,
                status: 'decomposing',
                streamingDecomposeText: ts.streamingDecomposeText + (data.content || ''),
              },
            },
          };
        }

        case 'decompose_progress': {
          const ts2 = s.taskStates[conversationId] || {
            status: 'decomposing', subTasks: [], activeAgents: [], agentLogs: [], streamingDecomposeText: '',
          };
          return {
            taskStates: {
              ...s.taskStates,
              [conversationId]: {
                ...ts2,
                status: 'decomposing',
                subTasks: (data.sub_tasks || []) as SubTask[],
              },
            },
          };
        }

        case 'assign_task': {
          const ts3 = s.taskStates[conversationId] || {
            status: 'executing', subTasks: [], activeAgents: [], agentLogs: [], streamingDecomposeText: '',
          };
          return {
            taskStates: {
              ...s.taskStates,
              [conversationId]: {
                ...ts3,
                status: 'executing',
                subTasks: ts3.subTasks.map(t =>
                  t.id === data.task_id
                    ? {
                        ...t,
                        state: data.state as SubTask['state'],
                        assigneeId: data.assignee_id as string,
                        dependencies: (data.dependencies as string[]) || t.dependencies,
                      }
                    : t
                ),
              },
            },
          };
        }

        case 'activate_agent': {
          const ts4 = s.taskStates[conversationId] || {
            status: 'executing', subTasks: [], activeAgents: [], agentLogs: [], streamingDecomposeText: '',
          };
          const newAgent: AgentActivity = {
            agentId: data.agent_id as string,
            agentName: data.agent_name as string,
            processTaskId: data.process_task_id as string,
            message: '',
          };
          const newLog: AgentLog = {
            agentId: data.agent_id as string,
            agentName: data.agent_name as string,
            processTaskId: data.process_task_id as string,
            status: 'running',
            inputMessage: (data.message as string) || '',
            outputMessage: '',
            timestamp: new Date().toISOString(),
          };
          return {
            taskStates: {
              ...s.taskStates,
              [conversationId]: {
                ...ts4,
                activeAgents: [...ts4.activeAgents, newAgent],
                agentLogs: [...(ts4.agentLogs || []), newLog],
              },
            },
          };
        }

        case 'deactivate_agent': {
          const ts5 = s.taskStates[conversationId] || {
            status: 'executing', subTasks: [], activeAgents: [], agentLogs: [], streamingDecomposeText: '',
          };
          const isError = typeof data.message === 'string' && data.message.startsWith('Error:');
          return {
            taskStates: {
              ...s.taskStates,
              [conversationId]: {
                ...ts5,
                activeAgents: ts5.activeAgents.filter(
                  a => a.agentId !== data.agent_id
                ),
                agentLogs: (ts5.agentLogs || []).map(log =>
                  log.agentId === data.agent_id
                    ? { ...log, status: isError ? 'error' as const : 'done' as const, outputMessage: (data.message as string) || '' }
                    : log
                ),
              },
            },
          };
        }

        case 'activate_toolkit': {
          const stepId = `${data.agent_name}_${data.method_name}_${Date.now()}`;
          return {
            agentSteps: {
              ...s.agentSteps,
              [conversationId]: [
                ...(s.agentSteps[conversationId] || []),
                {
                  id: stepId,
                  toolName: data.method_name as string,
                  toolArgs: { toolkit: data.toolkit_name, args: data.message },
                  status: 'running' as const,
                  timestamp: new Date().toISOString(),
                  agentName: data.agent_name as string,
                },
              ],
            },
          };
        }

        case 'deactivate_toolkit': {
          const steps = s.agentSteps[conversationId] || [];
          // Find the last running step with this method name
          const idx = [...steps].reverse().findIndex(
            st => st.toolName === data.method_name && st.status === 'running'
          );
          if (idx === -1) return {};
          const realIdx = steps.length - 1 - idx;
          return {
            agentSteps: {
              ...s.agentSteps,
              [conversationId]: steps.map((st, i) =>
                i === realIdx
                  ? { ...st, result: data.message as string, status: 'done' as const }
                  : st
              ),
            },
          };
        }

        case 'task_state': {
          const ts6 = s.taskStates[conversationId] || {
            status: 'executing', subTasks: [], activeAgents: [], agentLogs: [], streamingDecomposeText: '',
          };
          return {
            taskStates: {
              ...s.taskStates,
              [conversationId]: {
                ...ts6,
                subTasks: ts6.subTasks.map(t =>
                  t.id === data.task_id
                    ? { ...t, state: data.state as SubTask['state'], result: data.result as string }
                    : t
                ),
              },
            },
          };
        }

        case 'end': {
          const { [conversationId]: _end, ...restStreamingEnd } = s.streamingStates;
          const isActiveEnd = s.activeConversationId === conversationId;
          return {
            streamingStates: restStreamingEnd,
            ...(isActiveEnd ? {
              messages: [
                ...s.messages,
                {
                  id: `msg-${Date.now()}`,
                  conversation_id: conversationId,
                  role: 'assistant' as const,
                  content: data.content as string || '',
                  created_at: new Date().toISOString(),
                },
              ],
            } : {}),
            ...(data.conversation ? {
              conversations: sortConversations(
                s.conversations.map(c =>
                  c.id === (data.conversation as any).id ? data.conversation as any : c
                )
              ),
            } : {}),
            taskStates: {
              ...s.taskStates,
              [conversationId]: {
                ...(s.taskStates[conversationId] || { subTasks: [], activeAgents: [], agentLogs: [], streamingDecomposeText: '' }),
                status: 'done',
              },
            },
          };
        }

        case 'ask': {
          const tsAsk = s.taskStates[conversationId] || {
            status: 'executing', subTasks: [], activeAgents: [], agentLogs: [], streamingDecomposeText: '', pendingAsk: null,
          };
          return {
            taskStates: {
              ...s.taskStates,
              [conversationId]: {
                ...tsAsk,
                pendingAsk: {
                  agentName: data.agent_name as string,
                  question: data.question as string,
                  timestamp: new Date().toISOString(),
                },
              },
            },
          };
        }

        case 'skill_loaded':
        case 'insight_marked':
        case 'skill_evolved': {
          const tsSkill = s.taskStates[conversationId] || {
            status: 'executing' as const, subTasks: [], activeAgents: [], agentLogs: [], streamingDecomposeText: '', pendingAsk: null,
          };
          return {
            taskStates: {
              ...s.taskStates,
              [conversationId]: {
                ...tsSkill,
                agentLogs: [
                  ...(tsSkill.agentLogs || []),
                  {
                    agentId: String(data.agent || 'system'),
                    agentName: String(data.agent || 'Skill System'),
                    processTaskId: '',
                    status: 'done' as const,
                    inputMessage: step,
                    outputMessage: JSON.stringify(data),
                    timestamp: new Date().toISOString(),
                  },
                ],
              },
            },
          };
        }

        default:
          return {};
      }
    }),

  // Skills
  skills: [],
  activeSkill: null,
  skillStats: {},
  setSkills: (skills) => set({ skills }),
  setActiveSkill: (skill) => set({ activeSkill: skill }),
  setSkillStats: (stats) => {
    const map: Record<string, SkillStats> = {};
    for (const s of stats) map[s.name] = s;
    set({ skillStats: map });
  },
  updateSkillInList: (updated) =>
    set((s) => ({
      skills: s.skills.map((sk) => (sk.name === updated.name ? { ...sk, ...updated } : sk)),
    })),
  removeSkillFromList: (name) =>
    set((s) => ({
      skills: s.skills.filter((sk) => sk.name !== name),
    })),

  // Skills UI
  showSkills: false,
  setShowSkills: (show) => set({ showSkills: show, skillsView: { page: "list" } }),
  skillsView: { page: "list" },
  setSkillsView: (view) => set({ skillsView: view }),
}));
