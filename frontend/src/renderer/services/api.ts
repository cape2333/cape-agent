import type { Conversation, Message, AppSettings, ChatRequest, SSEEvent } from "../types";

let BASE_URL = "http://127.0.0.1:8001"; // overridden by initApiUrl()
let apiUrlPromise: Promise<string> | null = null;

export async function initApiUrl(): Promise<string> {
  if (!apiUrlPromise) {
    apiUrlPromise = (async () => {
      try {
        BASE_URL = await window.electronAPI.getBackendUrl();
      } catch {
        // fallback for dev
      }
      return BASE_URL;
    })();
  }

  return apiUrlPromise;
}

async function ensureApiUrl(): Promise<string> {
  return initApiUrl();
}

// --- Conversations ---

export async function fetchConversations(): Promise<Conversation[]> {
  await ensureApiUrl();
  const res = await fetch(`${BASE_URL}/api/conversations`);
  return res.json();
}

export async function createConversation(title?: string): Promise<Conversation> {
  await ensureApiUrl();
  const res = await fetch(`${BASE_URL}/api/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  return res.json();
}

export async function deleteConversation(id: string): Promise<void> {
  await ensureApiUrl();
  await fetch(`${BASE_URL}/api/conversations/${id}`, { method: "DELETE" });
}

export async function fetchMessages(conversationId: string): Promise<Message[]> {
  await ensureApiUrl();
  const res = await fetch(`${BASE_URL}/api/conversations/${conversationId}/messages`);
  return res.json();
}

// --- Settings ---

export async function fetchSettings(): Promise<AppSettings> {
  await ensureApiUrl();
  const res = await fetch(`${BASE_URL}/api/settings`);
  return res.json();
}

export async function updateSettings(settings: AppSettings): Promise<AppSettings> {
  await ensureApiUrl();
  const res = await fetch(`${BASE_URL}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  return res.json();
}

// --- Browser ---

export async function connectBrowser(cdpUrl: string): Promise<{ success: boolean; message: string; tool_count: number }> {
  await ensureApiUrl();
  const res = await fetch(`${BASE_URL}/api/browser/connect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cdp_url: cdpUrl }),
  });
  return res.json();
}

export async function disconnectBrowser(): Promise<{ success: boolean }> {
  await ensureApiUrl();
  const res = await fetch(`${BASE_URL}/api/browser/disconnect`, {
    method: "POST",
  });
  return res.json();
}

export async function getBrowserStatus(): Promise<{ connected: boolean; cdp_url?: string }> {
  await ensureApiUrl();
  const res = await fetch(`${BASE_URL}/api/browser/status`);
  return res.json();
}

// --- Streaming Chat ---

export interface ChatEventHandlers {
  onDelta: (content: string) => void;
  onDone: (fullContent: string, conversation?: Conversation) => void;
  onError: (error: string, conversation?: Conversation) => void;
  onToolStart?: (stepId: string, toolName: string, toolArgs: Record<string, unknown>) => void;
  onToolResult?: (stepId: string, toolName: string, toolResult: string) => void;
}

export async function sendChatMessage(
  req: ChatRequest,
  onDelta: (content: string) => void,
  onDone: (fullContent: string, conversation?: Conversation) => void,
  onError: (error: string, conversation?: Conversation) => void,
  onToolStart?: (stepId: string, toolName: string, toolArgs: Record<string, unknown>) => void,
  onToolResult?: (stepId: string, toolName: string, toolResult: string) => void,
): Promise<void> {
  await ensureApiUrl();
  const res = await fetch(`${BASE_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    onError(`HTTP ${res.status}: ${res.statusText}`);
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) {
    onError("No response body");
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data: ")) continue;
      try {
        const event: SSEEvent = JSON.parse(trimmed.slice(6));
        if (event.type === "delta") {
          onDelta(event.content);
        } else if (event.type === "done") {
          onDone(event.content, event.conversation);
        } else if (event.type === "error") {
          onError(event.content, event.conversation);
        } else if (event.type === "tool_start" && onToolStart) {
          onToolStart(
            event.step_id || "",
            event.tool_name || "",
            event.tool_args || {},
          );
        } else if (event.type === "tool_result" && onToolResult) {
          onToolResult(
            event.step_id || "",
            event.tool_name || "",
            event.tool_result || "",
          );
        }
      } catch {
        // skip malformed SSE
      }
    }
  }
}
