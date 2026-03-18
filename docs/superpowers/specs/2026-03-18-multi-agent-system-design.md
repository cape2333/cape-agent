# Multi-Agent System Design

## Overview

Refactor cape-agent from a single-agent architecture to a multi-agent system using CAMEL-AI's Workforce. When a user sends a message, an LLM classifier determines if the question is simple or complex. Simple questions stream a direct response via SSE (existing pattern). Complex questions are decomposed into subtasks and executed by specialized agents (browser, developer, document), with real-time SSE status streaming to the frontend.

## Scope (MVP)

**In scope:**
- LLM-based simple/complex question classification
- CAMEL Workforce-based task decomposition and execution
- 3 specialized agents: browser_agent, developer_agent, document_agent
- SSE streaming of all multi-agent lifecycle events
- Frontend display of task decomposition, agent activity, and progress
- Toolkits ported from Eigent: TerminalToolkit, FileToolkit, NoteTakingToolkit

**Out of scope (future iterations):**
- Task editing before execution (user confirmation flow)
- Pause/resume workforce
- Multi-turn workforce reuse (conversation context across tasks)
- Auto-confirm timer
- Dynamic agent creation
- MCP server integration
- Human-in-the-loop (ask agent)
- Timeout handling with notification

## Architecture

```
User Message (POST /api/chat)
    |
    v
+-----------------------------+
|  Chat Endpoint (chat.py)    |
|  - Save user message to DB  |
|  - Create TaskLock + Queue  |
|  - Start SSE event loop     |
+----------+------------------+
           |
           v
+-----------------------------+
|  Question Classifier Agent  |
|  (LLM-based routing)        |
|  -> "simple" or "complex"   |
+-----+----------------+------+
      |                |
   simple           complex
      |                |
      v                v
+----------+  +----------------------+
| Direct   |  | Workforce System     |
| SSE      |  | +------------------+ |
| streaming|  | | Coordinator      | |
| (existing|  | | (decompose task) | |
| pattern) |  | +--------+---------+ |
+----------+  |          v           |
              | +------------------+ |
              | | Task Assignment  | |
              | | & Execution      | |
              | | +==============+ | |
              | | |browser_agent | | |
              | | |dev_agent     | | |
              | | |doc_agent     | | |
              | | +==============+ | |
              | +------------------+ |
              +----------------------+
                     |
                     v (all events via TaskLock.queue)
              +------------------+
              | SSE Event Stream |
              +------------------+
```

## Backend File Structure

```
backend/app/
+-- api/
|   +-- chat.py              # Refactored: TaskLock + SSE event loop
|   +-- browser.py           # Unchanged
|   +-- conversations.py     # Unchanged
|   +-- settings.py          # Unchanged
+-- models/
|   +-- schemas.py           # Extended: new SSE event models
|   +-- database.py          # Unchanged
|   +-- enums.py             # NEW: Status, Action enums
+-- services/
|   +-- agent_service.py     # Refactored: classifier + workforce orchestration
|   +-- browser_service.py   # Unchanged
|   +-- conversation_service.py  # Unchanged
|   +-- task_lock.py         # NEW: TaskLock + Queue management
+-- agents/
|   +-- listen_chat_agent.py # NEW: ChatAgent with SSE event streaming
|   +-- workforce.py         # NEW: Custom Workforce subclass
|   +-- factory/
|       +-- browser.py       # NEW: Browser agent factory
|       +-- developer.py     # NEW: Developer agent factory
|       +-- document.py      # NEW: Document agent factory
|       +-- classifier.py    # NEW: Question classifier agent
+-- toolkits/
    +-- terminal.py          # NEW: Terminal toolkit (ported from Eigent)
    +-- file.py              # NEW: File toolkit (ported from Eigent)
    +-- note_taking.py       # NEW: Note-taking toolkit for cross-agent sharing
```

## SSE Event Protocol

All events use the format: `data: {"step": "<step>", "data": <payload>}\n\n`

### Simple Path Events

| Step | Payload | Description |
|------|---------|-------------|
| `delta` | `{"content": "chunk"}` | Streaming text chunk |
| `done` | `{"content": "full response", "conversation": {...}}` | Final complete response |
| `error` | `{"message": "error description"}` | Error occurred |

### Complex Path Events

#### Decomposition Phase

| Step | Payload | Description |
|------|---------|-------------|
| `decompose_text` | `{"content": "chunk"}` | Streaming decomposition thinking |
| `decompose_progress` | `{"sub_tasks": [{"id", "content", "state"}], "is_final": bool}` | Subtask list (incremental or final) |

#### Execution Phase

| Step | Payload | Description |
|------|---------|-------------|
| `assign_task` | `{"task_id", "assignee_id", "content", "state": "waiting"\|"running"}` | Task assigned to agent |
| `activate_agent` | `{"agent_name", "agent_id", "process_task_id", "message": ""}` | Agent started working |
| `activate_toolkit` | `{"agent_name", "toolkit_name", "method_name", "message"}` | Tool execution started |
| `deactivate_toolkit` | `{"agent_name", "toolkit_name", "method_name", "message": "result"}` | Tool execution finished |
| `deactivate_agent` | `{"agent_name", "agent_id", "process_task_id", "message": "full response"}` | Agent finished |
| `task_state` | `{"task_id", "state": "DONE"\|"FAILED", "result", "content"}` | Subtask completed/failed |
| `terminal` | `{"content": "output", "process_task_id"}` | Terminal command output |
| `write_file` | `{"file_path", "content", "process_task_id"}` | File created/written |

#### Completion

| Step | Payload | Description |
|------|---------|-------------|
| `end` | `{"content": "final summary", "conversation": {...}}` | Workflow complete |

## Core Components

### TaskLock

Central state holder for an active chat session. Owns the asyncio.Queue that bridges backend events to the SSE endpoint.

```python
class TaskLock:
    id: str                          # conversation_id
    status: Status                   # classifying | decomposing | executing | done
    queue: asyncio.Queue[dict]       # {"step": str, "data": dict} events
    workforce: CapeWorkforce | None  # Active workforce instance (complex path only)

    async def put_event(self, step: str, data: dict):
        await self.queue.put({"step": step, "data": data})

    async def get_event(self) -> dict:
        return await self.queue.get()
```

**Status enum:**
```python
class Status(str, Enum):
    classifying = "classifying"    # Running question classifier
    decomposing = "decomposing"    # Workforce decomposing task
    executing = "executing"        # Workforce executing subtasks
    done = "done"                  # Complete
```

### CapeWorkforce (Custom Workforce Subclass)

Extends CAMEL's `BaseWorkforce` with SSE event emission at each lifecycle point.

```python
class CapeWorkforce(BaseWorkforce):
    task_lock: TaskLock

    async def _find_assignee(self, tasks) -> TaskAssignResult:
        """Override: emit assign_task with state='waiting' for each assignment."""
        result = await super()._find_assignee(tasks)
        for assignment in result.assignments:
            await self.task_lock.put_event("assign_task", {
                "task_id": assignment.task_id,
                "assignee_id": self._resolve_agent_name(assignment.assignee_id),
                "content": self._get_task_content(assignment.task_id),
                "state": "waiting",
            })
        return result

    async def _post_task(self, task, assignee_id):
        """Override: emit assign_task with state='running'."""
        await self.task_lock.put_event("assign_task", {
            "task_id": task.id,
            "assignee_id": self._resolve_agent_name(assignee_id),
            "content": task.content,
            "state": "running",
        })
        await super()._post_task(task, assignee_id)

    async def _handle_completed_task(self, task):
        """Override: emit task_state with DONE."""
        await self.task_lock.put_event("task_state", {
            "task_id": task.id,
            "state": "DONE",
            "result": task.result,
            "content": task.content,
        })
        await super()._handle_completed_task(task)

    async def _handle_failed_task(self, task) -> bool:
        """Override: emit task_state with FAILED after max retries."""
        result = await super()._handle_failed_task(task)
        await self.task_lock.put_event("task_state", {
            "task_id": task.id,
            "state": "FAILED",
            "result": str(task.result),
            "content": task.content,
        })
        return result
```

**Decomposition:** Uses CAMEL's coordinator agent to break complex questions into subtasks. Streams decomposition text via `decompose_text` events and emits `decompose_progress` when subtasks are finalized.

### ListenChatAgent

Extends CAMEL's `ChatAgent` with per-agent SSE event streaming.

```python
class ListenChatAgent(ChatAgent):
    task_lock: TaskLock
    agent_name: str              # "Browser Agent", "Developer Agent", etc.
    process_task_id: str = ""    # Set by SingleAgentWorker before execution

    # Emits activate_agent when astep() starts
    # Emits activate_toolkit / deactivate_toolkit on each tool call
    # Emits deactivate_agent when astep() completes (with full response text)
```

**Tool event tracking:** Overrides `_aexecute_tool()` and `_aexecute_tool_from_stream_data()` (like current CapeAgent) but emits `activate_toolkit`/`deactivate_toolkit` instead of `tool_start`/`tool_result`.

### SingleAgentWorker

Bridges CAMEL's Workforce task assignment to ListenChatAgent execution.

```python
class SingleAgentWorker:
    agent: ListenChatAgent
    description: str             # Used by Workforce for task matching

    async def process_task(self, task: Task, dependencies: list[Task]) -> TaskState:
        self.agent.process_task_id = task.id
        prompt = self._build_prompt(task, dependencies)
        response = await self.agent.astep(prompt)
        # Parse structured result
        return TaskState.DONE if success else TaskState.FAILED
```

### Agent Factories

Each factory creates a configured ListenChatAgent with appropriate tools and system prompt.

#### Browser Agent Factory
```python
def create_browser_agent(task_lock, model_config) -> ListenChatAgent:
    tools = browser_service.get_tools()  # HybridBrowserToolkit from existing service
    return ListenChatAgent(
        task_lock=task_lock,
        agent_name="Browser Agent",
        system_message=BROWSER_SYSTEM_PROMPT,
        tools=tools,
        model=model_config,
    )
```

System prompt: Senior Research Analyst role. Web search and browsing specialist. Uses HybridBrowserToolkit (existing CDP integration) + NoteTakingToolkit for sharing findings.

#### Developer Agent Factory
```python
def create_developer_agent(task_lock, model_config) -> ListenChatAgent:
    terminal_toolkit = TerminalToolkit(task_lock=task_lock)
    note_toolkit = NoteTakingToolkit(task_lock=task_lock)
    tools = terminal_toolkit.get_tools() + note_toolkit.get_tools()
    return ListenChatAgent(
        task_lock=task_lock,
        agent_name="Developer Agent",
        system_message=DEVELOPER_SYSTEM_PROMPT,
        tools=tools,
        model=model_config,
    )
```

System prompt: Lead Software Engineer role. Code execution and technical implementation. Uses TerminalToolkit (shell_exec, file operations) + NoteTakingToolkit for sharing results.

#### Document Agent Factory
```python
def create_document_agent(task_lock, model_config) -> ListenChatAgent:
    file_toolkit = FileToolkit(task_lock=task_lock)
    note_toolkit = NoteTakingToolkit(task_lock=task_lock)
    tools = file_toolkit.get_tools() + note_toolkit.get_tools()
    return ListenChatAgent(
        task_lock=task_lock,
        agent_name="Document Agent",
        system_message=DOCUMENT_SYSTEM_PROMPT,
        tools=tools,
        model=model_config,
    )
```

System prompt: Documentation Specialist role. Document creation and management. Uses FileToolkit (write_to_file for Markdown, HTML, CSV, JSON) + NoteTakingToolkit for cross-agent info sharing.

#### Question Classifier Agent
```python
def create_classifier_agent(model_config) -> ChatAgent:
    return ChatAgent(
        system_message=CLASSIFIER_PROMPT,
        model=model_config,
    )
    # No tools - lightweight classification only
    # Returns structured output: {"type": "simple" | "complex", "reason": "..."}
```

System prompt: Analyzes user request complexity. Returns "simple" for direct Q&A, greetings, factual questions. Returns "complex" for multi-step tasks requiring tools, research, code, or document creation.

### Toolkits (Ported from Eigent)

#### TerminalToolkit
- `shell_exec(command: str) -> str` - Execute shell commands with safe mode
- Environment cloning from current process
- Emits `terminal` SSE events for command output
- Working directory management

#### FileToolkit
- `write_to_file(path: str, content: str) -> str` - Create/write documents
- UTF-8 encoding support
- Emits `write_file` SSE events
- Supports Markdown, HTML, CSV, JSON, YAML formats

#### NoteTakingToolkit
- `create_note(title: str, content: str)` - Create a note for other agents
- `read_note(title: str) -> str` - Read a note from any agent
- `list_note() -> list[str]` - List all available notes
- `append_note(title: str, content: str)` - Append to existing note
- Shared `shared_files` note for tracking generated files
- In-memory storage scoped to the TaskLock lifetime

## Chat Endpoint Flow (Refactored)

```python
# POST /api/chat
async def chat(request: ChatRequest):
    # 1. Validate conversation exists
    # 2. Save user message to DB
    # 3. Load conversation history

    async def event_stream():
        # 4. Create TaskLock
        task_lock = TaskLock(id=request.conversation_id)

        # 5. Classify question
        classifier = create_classifier_agent(model_config)
        classification = await classify_question(classifier, request.message, history)

        if classification == "simple":
            # 6a. Simple path: direct streaming (existing pattern)
            agent = build_simple_agent(history, model_config)
            async for event in agent_chat(agent, request.message):
                yield sse_json(event["step"], event["data"])
        else:
            # 6b. Complex path: workforce
            workforce = build_workforce(task_lock, model_config)

            # Start workforce decomposition + execution in background
            bg_task = asyncio.create_task(
                workforce.decompose_and_execute(request.message)
            )

            # Consume events from TaskLock queue
            while True:
                event = await task_lock.get_event()
                yield sse_json(event["step"], event["data"])
                if event["step"] == "end":
                    # Save assistant message to DB
                    await save_assistant_message(event["data"]["content"])
                    break

            await bg_task  # Ensure cleanup

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

## Workforce Builder

```python
def build_workforce(task_lock: TaskLock, model_config) -> CapeWorkforce:
    # Create coordinator agent (for task decomposition)
    coordinator = ChatAgent(
        system_message="You are a task decomposition expert...",
        model=model_config,
    )

    # Create task agent (for subtask refinement)
    task_agent = ChatAgent(
        system_message="You refine subtasks for clarity...",
        model=model_config,
    )

    # Create workforce
    workforce = CapeWorkforce(
        task_lock=task_lock,
        description="Cape Agent Workforce",
        coordinator_agent=coordinator,
        task_agent=task_agent,
    )

    # Add specialized workers
    browser_agent = create_browser_agent(task_lock, model_config)
    workforce.add_single_agent_worker(
        description="Web research, browsing, and information gathering",
        worker=browser_agent,
    )

    developer_agent = create_developer_agent(task_lock, model_config)
    workforce.add_single_agent_worker(
        description="Code writing, execution, and technical implementation",
        worker=developer_agent,
    )

    document_agent = create_document_agent(task_lock, model_config)
    workforce.add_single_agent_worker(
        description="Document creation, file management, and content writing",
        worker=document_agent,
    )

    return workforce
```

## Frontend Changes

### Extended SSE Event Format

```typescript
// New unified event interface (replaces old SSEEvent)
interface SSEEvent {
  step: string;   // Event type (was "type")
  data: any;      // Step-specific payload
}
```

### Extended Zustand Store

New state slice for task tracking (per conversation):

```typescript
// New types
interface SubTask {
  id: string;
  content: string;
  state: 'open' | 'waiting' | 'running' | 'DONE' | 'FAILED';
  assigneeId?: string;
  result?: string;
}

interface AgentActivity {
  agentId: string;
  agentName: string;
  processTaskId: string;
  message: string;
}

// New store state (per conversation)
taskState: Record<conversationId, {
  status: 'idle' | 'classifying' | 'decomposing' | 'executing' | 'done';
  subTasks: SubTask[];
  activeAgents: AgentActivity[];
  streamingDecomposeText: string;
}>
```

### SSE Event Handler (api.ts)

Replace specific callbacks with a single `onEvent` handler:

```typescript
export async function sendChatMessage(
  req: ChatRequest,
  onEvent: (event: SSEEvent) => void,
): Promise<void>
```

The Zustand store's `handleSSEEvent(conversationId, event)` method dispatches based on `event.step`:

| Step | Store Action |
|------|-------------|
| `delta` | `appendStreamChunk(conversationId, data.content)` |
| `done` | `finalizeStream(conversationId, data.content)` |
| `decompose_text` | `appendDecomposeText(conversationId, data.content)` |
| `decompose_progress` | `setSubTasks(conversationId, data.sub_tasks)` |
| `assign_task` | `updateSubTask(conversationId, data.task_id, data)` |
| `activate_agent` | `addActiveAgent(conversationId, data)` |
| `deactivate_agent` | `removeActiveAgent(conversationId, data.agent_id)` |
| `activate_toolkit` | `addAgentStep(conversationId, ...)` (reuse existing) |
| `deactivate_toolkit` | `updateAgentStep(conversationId, ...)` (reuse existing) |
| `task_state` | `updateSubTask(conversationId, data.task_id, data)` |
| `terminal` | `addAgentStep(conversationId, {toolName: "terminal", ...})` |
| `write_file` | `addAgentStep(conversationId, {toolName: "write_file", ...})` |
| `end` | `setTaskStatus(conversationId, 'done'); finalizeStream(...)` |
| `error` | `finalizeStream(conversationId, error message)` |

### New UI Components

#### TaskProgress Component

Displayed above StreamingMessage when in workforce mode. Shows:
- List of subtasks with status indicators (icon per state: spinner=running, check=done, x=failed, clock=waiting)
- Which agent is assigned to each subtask
- Overall progress bar (completed/total subtasks)

#### Extended StreamingMessage

When `taskState.status !== 'idle'`, StreamingMessage renders additional sections:
- Decomposition streaming text (during decomposing phase)
- TaskProgress component (during executing phase)
- Agent steps per active agent (reusing existing AgentStep display)

Existing MessageBubble, ChatArea, InputBar, Sidebar components remain unchanged.

## Migration Notes

### Backward Compatibility

- The simple path preserves the existing SSE behavior (`delta`/`done`/`error`)
- The `tool_start`/`tool_result` events are replaced by `activate_toolkit`/`deactivate_toolkit` in the complex path, but the simple path agent can still use the existing pattern
- Conversation DB schema unchanged
- Settings API unchanged
- Browser connect/disconnect API unchanged

### Files Modified

| File | Change |
|------|--------|
| `backend/app/api/chat.py` | Major refactor: add classifier, TaskLock, workforce path |
| `backend/app/services/agent_service.py` | Simplify: remove CapeAgent class, keep build_simple_agent + agent_chat for simple path |
| `backend/app/models/schemas.py` | Add SSE event data models, sse_json helper |
| `frontend/src/renderer/services/api.ts` | Change SSEEvent format, switch to single onEvent callback |
| `frontend/src/renderer/stores/store.ts` | Add taskState slice, handleSSEEvent dispatcher |
| `frontend/src/renderer/hooks/useChat.ts` | Update to use new onEvent callback pattern |
| `frontend/src/renderer/components/chat/StreamingMessage.tsx` | Extend for workforce mode display |
| `frontend/src/renderer/types/index.ts` | Add SubTask, AgentActivity, extended types |

### Files Created

| File | Purpose |
|------|---------|
| `backend/app/models/enums.py` | Status enum |
| `backend/app/services/task_lock.py` | TaskLock class with asyncio.Queue |
| `backend/app/agents/listen_chat_agent.py` | ChatAgent with SSE event streaming |
| `backend/app/agents/workforce.py` | CapeWorkforce subclass |
| `backend/app/agents/factory/browser.py` | Browser agent factory |
| `backend/app/agents/factory/developer.py` | Developer agent factory |
| `backend/app/agents/factory/document.py` | Document agent factory |
| `backend/app/agents/factory/classifier.py` | Question classifier factory |
| `backend/app/toolkits/terminal.py` | TerminalToolkit (ported from Eigent) |
| `backend/app/toolkits/file.py` | FileToolkit (ported from Eigent) |
| `backend/app/toolkits/note_taking.py` | NoteTakingToolkit for cross-agent sharing |
| `frontend/src/renderer/components/chat/TaskProgress.tsx` | Subtask progress display |
