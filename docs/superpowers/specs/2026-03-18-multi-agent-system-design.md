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
- Toolkits from CAMEL built-in: TerminalToolkit, FileToolkit, NoteTakingToolkit

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
|   +-- schemas.py           # Extended: new SSE event models, sse_json helper
|   +-- database.py          # Unchanged
|   +-- enums.py             # NEW: Status enum
+-- services/
|   +-- agent_service.py     # Refactored: classifier + workforce orchestration
|   +-- browser_service.py   # Unchanged
|   +-- conversation_service.py  # Unchanged
|   +-- task_lock.py         # NEW: TaskLock + Queue management
+-- agents/
|   +-- listen_chat_agent.py # NEW: ChatAgent with SSE event streaming
|   +-- workforce.py         # NEW: CapeWorkforce subclass + CapeWorkforceCallback
|   +-- single_agent_worker.py # NEW: CapeAgentWorker bridge
|   +-- factory/
|       +-- browser.py       # NEW: Browser agent factory
|       +-- developer.py     # NEW: Developer agent factory
|       +-- document.py      # NEW: Document agent factory
|       +-- classifier.py    # NEW: Question classifier agent
```

## SSE Event Protocol

All events use a unified envelope format: `data: {"step": "<step>", "data": <payload>}\n\n`

Both simple and complex paths use the same `{"step", "data"}` envelope. The old `{"type", "content"}` format is retired.

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
| `task_state` | `{"task_id", "state": "done"\|"failed", "result", "content"}` | Subtask completed/failed |
| `terminal` | `{"content": "output", "process_task_id"}` | Terminal command output |
| `write_file` | `{"file_path", "content", "process_task_id"}` | File created/written |

All task state values use lowercase (`done`, `failed`, `waiting`, `running`, `open`). CAMEL's uppercase `TaskState` enum values are converted to lowercase at the event emission boundary.

#### Completion

| Step | Payload | Description |
|------|---------|-------------|
| `end` | `{"content": "final summary", "conversation": {...}}` | Workflow complete |

#### Error Handling

The `error` step is used across both paths. In the complex path, errors can originate from:
- Classification failure: `{"message": "Failed to classify question: ..."}`
- Decomposition failure: `{"message": "Failed to decompose task: ..."}`
- Workforce execution failure: `{"message": "Workforce error: ..."}`
- Individual agent failure: Handled via `task_state` with `state: "failed"`, not via `error`

## Core Components

### TaskLock

Central state holder for an active chat session. Owns the asyncio.Queue that bridges backend events to the SSE endpoint.

```python
@dataclass
class TaskLock:
    id: str                          # conversation_id
    status: Status                   # classifying | decomposing | executing | done
    queue: asyncio.Queue[dict]       # {"step": str, "data": dict} events
    workforce: Workforce | None = None  # Active workforce (complex path only)
    working_directory: str = ""  # Shared working dir for toolkits (notes, files)
    background_tasks: set[asyncio.Task] = field(default_factory=set)  # Track bg tasks for cleanup

    async def put_event(self, step: str, data: dict):
        await self.queue.put({"step": step, "data": data})

    async def get_event(self) -> dict:
        return await self.queue.get()

    async def cleanup(self):
        """Cancel background tasks and stop workforce on disconnect or error."""
        if self.workforce:
            self.workforce.stop()  # Workforce.stop() is synchronous
        for task in self.background_tasks:
            task.cancel()
        # Drain remaining queue items
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
```

**Status enum:**
```python
class Status(str, Enum):
    classifying = "classifying"    # Running question classifier
    decomposing = "decomposing"    # Workforce decomposing task
    executing = "executing"        # Workforce executing subtasks
    done = "done"                  # Complete
```

### CapeWorkforceCallback (Using CAMEL's Callback System)

Instead of overriding internal Workforce methods, we use CAMEL's built-in `WorkforceCallback` system for task-level SSE events. This is the primary mechanism for emitting events to the frontend.

```python
from camel.societies.workforce.workforce_callback import WorkforceCallback
from camel.societies.workforce.events import (
    TaskCreatedEvent,
    TaskDecomposedEvent,
    TaskAssignedEvent,
    TaskStartedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    AllTasksCompletedEvent,
    WorkerCreatedEvent,
    WorkerDeletedEvent,
)

class CapeWorkforceCallback(WorkforceCallback):
    """Translates CAMEL Workforce lifecycle events into SSE events."""

    def __init__(self, task_lock: TaskLock):
        self.task_lock = task_lock
        self._loop = asyncio.get_event_loop()

    def _emit(self, step: str, data: dict):
        """Schedule an async put_event from sync callback context."""
        asyncio.run_coroutine_threadsafe(
            self.task_lock.put_event(step, data),
            self._loop,
        )

    def log_task_created(self, event: TaskCreatedEvent) -> None:
        """Emitted when a subtask is created during decomposition."""
        # Handled via decompose_progress in _decompose_task override
        pass

    def log_task_decomposed(self, event: TaskDecomposedEvent) -> None:
        """Emitted when task decomposition completes."""
        self._emit("decompose_progress", {
            "sub_tasks": [
                {"id": t.id, "content": t.content, "state": "open"}
                for t in event.subtasks
            ],
            "is_final": True,
        })

    def log_task_assigned(self, event: TaskAssignedEvent) -> None:
        """Emitted when a subtask is assigned to a worker."""
        self._emit("assign_task", {
            "task_id": event.task_id,
            "assignee_id": event.worker_description or event.assignee_id,
            "content": event.task_content,
            "state": "waiting",
        })

    def log_task_started(self, event: TaskStartedEvent) -> None:
        """Emitted when a worker begins executing an assigned task."""
        self._emit("assign_task", {
            "task_id": event.task_id,
            "assignee_id": event.worker_description or event.assignee_id,
            "content": event.task_content,
            "state": "running",
        })

    def log_task_completed(self, event: TaskCompletedEvent) -> None:
        """Emitted when a subtask completes successfully."""
        self._emit("task_state", {
            "task_id": event.task_id,
            "state": "done",
            "result": event.result,
            "content": event.task_content,
        })

    def log_task_failed(self, event: TaskFailedEvent) -> None:
        """Emitted when a subtask fails."""
        self._emit("task_state", {
            "task_id": event.task_id,
            "state": "failed",
            "result": str(event.error),
            "content": event.task_content,
        })

    def log_worker_created(self, event: WorkerCreatedEvent) -> None:
        pass  # Not needed for MVP

    def log_worker_deleted(self, event: WorkerDeletedEvent) -> None:
        pass  # Not needed for MVP

    def log_all_tasks_completed(self, event: AllTasksCompletedEvent) -> None:
        """Emitted when all subtasks are done -- workforce is complete."""
        # Build final summary from completed tasks
        results = []
        for task_result in event.task_results:
            results.append(f"- {task_result.content}: {task_result.result}")
        summary = "\n".join(results) if results else "Task completed."

        self._emit("end", {"content": summary})
```

**Note on sync/async bridging:** CAMEL's `WorkforceCallback` methods are synchronous, but our `TaskLock.put_event()` is async. We use `asyncio.run_coroutine_threadsafe()` to schedule the async put from the sync callback context. This is safe because the workforce runs in the same event loop.

### CapeWorkforce (Minimal Subclass)

With callbacks handling most events, the workforce subclass only needs to add decomposition streaming.

```python
from camel.societies.workforce import Workforce
from camel.tasks import Task

class CapeWorkforce(Workforce):
    """Extends Workforce with SSE streaming during task decomposition."""

    task_lock: TaskLock

    def __init__(self, task_lock: TaskLock, **kwargs):
        # Register our callback
        callback = CapeWorkforceCallback(task_lock)
        super().__init__(callbacks=[callback], **kwargs)
        self.task_lock = task_lock

    async def run(self, question: str):
        """Entry point: decompose with streaming, then execute via process_task_async.

        Uses CAMEL's process_task_async() which handles the full lifecycle:
        reset, channel creation, task decomposition, assignment, execution,
        and all lifecycle callbacks.
        """
        # Create the main task
        main_task = Task(content=question, id=f"main_{uuid4().hex[:8]}")

        self.task_lock.status = Status.decomposing

        # Override _decompose_task to add streaming before process_task_async runs
        original_decompose = self._decompose_task

        async def streaming_decompose(task):
            """Wrapper that streams decomposition text to frontend."""
            # Call the original decomposition
            subtasks = await original_decompose(task)
            # Emit streaming events handled by callback (log_task_decomposed)
            return subtasks

        self._decompose_task = streaming_decompose

        try:
            self.task_lock.status = Status.executing
            # process_task_async handles everything:
            # - reset()
            # - set_channel(TaskChannel())
            # - handle_decompose_append_task(task) -> _decompose_task()
            # - start() -> assignment + execution loop
            # - lifecycle callbacks fire throughout
            result = await self.process_task_async(main_task)
            return result
        except Exception as e:
            await self.task_lock.put_event("error", {
                "message": f"Workforce error: {str(e)}"
            })
            raise
```

**Key design decision:** We use `process_task_async()` as the single entry point rather than manually calling `reset()`, `set_channel()`, `handle_decompose_append_task()`, and `start()`. This avoids reproducing CAMEL's internal initialization logic and stays resilient to CAMEL API changes. Lifecycle events are emitted via the `CapeWorkforceCallback`.

### ListenChatAgent

Extends CAMEL's `ChatAgent` with per-agent SSE event streaming for activate/deactivate agent events and per-tool-call toolkit events. The callback system handles task-level events; this class handles agent-level events.

```python
class ListenChatAgent(ChatAgent):
    task_lock: TaskLock
    agent_name: str              # "Browser Agent", "Developer Agent", etc.
    agent_id: str                # Unique ID for this agent instance
    process_task_id: str = ""    # Set by CapeAgentWorker before execution

    def __init__(self, task_lock: TaskLock, agent_name: str, **kwargs):
        super().__init__(**kwargs)
        self.task_lock = task_lock
        self.agent_name = agent_name
        self.agent_id = f"{agent_name.lower().replace(' ', '_')}_{uuid4().hex[:8]}"

    async def astep(self, input_message, **kwargs):
        """Override: wrap astep with activate/deactivate agent events.

        Does NOT yield/stream -- returns the response object directly.
        The activate_agent event fires before execution starts.
        The deactivate_agent event fires after execution completes (or errors).
        """
        # Emit activate_agent
        await self.task_lock.put_event("activate_agent", {
            "agent_name": self.agent_name,
            "agent_id": self.agent_id,
            "process_task_id": self.process_task_id,
            "message": "",
        })

        try:
            response = await super().astep(input_message, **kwargs)

            # Extract final message content
            final_message = ""
            if hasattr(response, 'msg') and response.msg:
                final_message = response.msg.content or ""

            # Emit deactivate_agent with full response
            await self.task_lock.put_event("deactivate_agent", {
                "agent_name": self.agent_name,
                "agent_id": self.agent_id,
                "process_task_id": self.process_task_id,
                "message": final_message,
            })

            return response
        except Exception as e:
            # Emit deactivate on error too
            await self.task_lock.put_event("deactivate_agent", {
                "agent_name": self.agent_name,
                "agent_id": self.agent_id,
                "process_task_id": self.process_task_id,
                "message": f"Error: {str(e)}",
            })
            raise

    async def _aexecute_tool(self, tool_call_request: ToolCallRequest) -> ToolCallingRecord:
        """Override: emit activate_toolkit / deactivate_toolkit events.

        Parameter is ToolCallRequest with .tool_name and .args attributes.
        """
        tool_name = tool_call_request.tool_name
        toolkit_name = self._resolve_toolkit_name(tool_name)
        tool_args = str(tool_call_request.args)[:200]  # Truncate large args

        await self.task_lock.put_event("activate_toolkit", {
            "agent_name": self.agent_name,
            "toolkit_name": toolkit_name,
            "method_name": tool_name,
            "message": tool_args,
        })

        try:
            result = await super()._aexecute_tool(tool_call_request)

            await self.task_lock.put_event("deactivate_toolkit", {
                "agent_name": self.agent_name,
                "toolkit_name": toolkit_name,
                "method_name": tool_name,
                "message": str(result)[:500],  # Truncate large results
            })
            return result
        except Exception as e:
            await self.task_lock.put_event("deactivate_toolkit", {
                "agent_name": self.agent_name,
                "toolkit_name": toolkit_name,
                "method_name": tool_name,
                "message": f"Error: {str(e)}",
            })
            raise

    async def _aexecute_tool_from_stream_data(
        self, tool_call_data: dict[str, Any]
    ) -> ToolCallingRecord | None:
        """Override: same pattern for streaming tool calls.

        tool_call_data structure: {"function": {"name": ..., "arguments": ...}, "id": ...}
        """
        tool_name = tool_call_data["function"]["name"]
        toolkit_name = self._resolve_toolkit_name(tool_name)
        tool_args = tool_call_data["function"].get("arguments", "")

        await self.task_lock.put_event("activate_toolkit", {
            "agent_name": self.agent_name,
            "toolkit_name": toolkit_name,
            "method_name": tool_name,
            "message": str(tool_args)[:200],
        })

        try:
            result = await super()._aexecute_tool_from_stream_data(tool_call_data)

            await self.task_lock.put_event("deactivate_toolkit", {
                "agent_name": self.agent_name,
                "toolkit_name": toolkit_name,
                "method_name": tool_name,
                "message": str(result)[:500],
            })
            return result
        except Exception as e:
            await self.task_lock.put_event("deactivate_toolkit", {
                "agent_name": self.agent_name,
                "toolkit_name": toolkit_name,
                "method_name": tool_name,
                "message": f"Error: {str(e)}",
            })
            raise

    def _resolve_toolkit_name(self, tool_name: str) -> str:
        """Map tool function name to toolkit name.

        Examples:
          'browser_click' -> 'browser'
          'shell_exec' -> 'terminal'
          'write_to_file' -> 'file'
          'create_note' -> 'note_taking'
        """
        # Use the first segment before underscore as toolkit name
        # This matches the naming convention of CAMEL tools
        return tool_name.split('_')[0] if '_' in tool_name else tool_name
```

### CapeAgentWorker (SingleAgentWorker Bridge)

Bridges CAMEL's Workforce task assignment to ListenChatAgent execution. Extends CAMEL's `SingleAgentWorker` to use our custom `ListenChatAgent`.

```python
from camel.workforce import SingleAgentWorker
from camel.tasks import Task, TaskState

PROCESS_TASK_PROMPT = """You are assigned the following task:

**Task:** {content}

**Parent Task Context:** {parent_task_content}

**Dependency Results:**
{dependency_tasks_info}

Complete this task thoroughly. When done, provide your result as a clear,
actionable summary of what was accomplished.
"""

class CapeAgentWorker(SingleAgentWorker):
    """Custom worker that sets process_task_id and builds structured prompts."""

    def __init__(self, description: str, worker: ListenChatAgent, **kwargs):
        super().__init__(description=description, worker=worker, **kwargs)
        self._cape_worker = worker  # Keep typed reference

    async def _process_task(self, task: Task, dependencies: list[Task]) -> TaskState:
        """Execute a subtask with full prompt context.

        1. Set process_task_id on the agent (for SSE event correlation)
        2. Build prompt from task content + dependency results
        3. Call agent.astep() (which emits activate/deactivate events)
        4. Parse response for success/failure
        5. Set task.result
        """
        self._cape_worker.process_task_id = task.id

        # Build prompt with dependency info
        dep_info = self._format_dependencies(dependencies)
        parent_content = task.parent.content if task.parent else "N/A"

        prompt = PROCESS_TASK_PROMPT.format(
            content=task.content,
            parent_task_content=parent_content,
            dependency_tasks_info=dep_info if dep_info else "None",
        )

        try:
            response = await self._cape_worker.astep(prompt)

            # Extract content from response
            response_content = ""
            if hasattr(response, 'msg') and response.msg:
                response_content = response.msg.content or ""

            task.result = response_content
            return TaskState.DONE

        except Exception as e:
            task.result = f"Failed: {str(e)}"
            return TaskState.FAILED

    def _format_dependencies(self, dependencies: list[Task]) -> str:
        """Format dependency task results for the prompt."""
        if not dependencies:
            return ""
        lines = []
        for dep in dependencies:
            result = dep.result if dep.result else "No result"
            lines.append(f"- [{dep.id}] {dep.content}: {result}")
        return "\n".join(lines)
```

### Agent Factories

Each factory creates a configured ListenChatAgent with appropriate tools and system prompt. The `model` parameter is the return value of `ModelFactory.create()` -- a pre-built CAMEL model object (`BaseModelBackend`) shared across all agents in the workforce.

#### Browser Agent Factory
```python
def create_browser_agent(task_lock: TaskLock, model: BaseModelBackend) -> ListenChatAgent:
    browser_tools = browser_service.get_tools()  # HybridBrowserToolkit from existing service
    note_toolkit = NoteTakingToolkit(task_lock=task_lock)
    tools = browser_tools + note_toolkit.get_tools()
    return ListenChatAgent(
        task_lock=task_lock,
        agent_name="Browser Agent",
        system_message=BaseMessage.make_assistant_message(
            role_name="Browser Agent",
            content=BROWSER_SYSTEM_PROMPT,
        ),
        tools=tools,
        model=model,
    )
```

System prompt: Senior Research Analyst role. Web search and browsing specialist. Uses HybridBrowserToolkit (existing CDP integration) + NoteTakingToolkit for sharing findings.

#### Developer Agent Factory
```python
from camel.toolkits.terminal_toolkit import TerminalToolkit
from camel.toolkits import NoteTakingToolkit

def create_developer_agent(task_lock: TaskLock, model: BaseModelBackend,
                           working_directory: str) -> ListenChatAgent:
    terminal_toolkit = TerminalToolkit(
        working_directory=working_directory,
        safe_mode=True,
        clone_current_env=True,
        timeout=30.0,
    )
    note_toolkit = NoteTakingToolkit(
        working_directory=working_directory,
    )
    tools = terminal_toolkit.get_tools() + note_toolkit.get_tools()
    return ListenChatAgent(
        task_lock=task_lock,
        agent_name="Developer Agent",
        system_message=BaseMessage.make_assistant_message(
            role_name="Developer Agent",
            content=DEVELOPER_SYSTEM_PROMPT,
        ),
        tools=tools,
        model=model,
    )
```

System prompt: Lead Software Engineer role. Code execution and technical implementation. Uses CAMEL's `TerminalToolkit` (shell_exec, shell_view, process management) + `NoteTakingToolkit` for sharing results.

#### Document Agent Factory
```python
from camel.toolkits import FileToolkit, NoteTakingToolkit

def create_document_agent(task_lock: TaskLock, model: BaseModelBackend,
                          working_directory: str) -> ListenChatAgent:
    file_toolkit = FileToolkit(
        working_directory=working_directory,
        default_encoding="utf-8",
        backup_enabled=True,
    )
    note_toolkit = NoteTakingToolkit(
        working_directory=working_directory,
    )
    tools = file_toolkit.get_tools() + note_toolkit.get_tools()
    return ListenChatAgent(
        task_lock=task_lock,
        agent_name="Document Agent",
        system_message=BaseMessage.make_assistant_message(
            role_name="Document Agent",
            content=DOCUMENT_SYSTEM_PROMPT,
        ),
        tools=tools,
        model=model,
    )
```

System prompt: Documentation Specialist role. Document creation and management. Uses CAMEL's `FileToolkit` (write_to_file, read_file, edit_file, search_files — supports Markdown, HTML, CSV, JSON, YAML, PDF, Word) + `NoteTakingToolkit` for cross-agent info sharing.

#### Question Classifier Agent
```python
def create_classifier_agent(model: BaseModelBackend) -> ChatAgent:
    return ChatAgent(
        system_message=BaseMessage.make_assistant_message(
            role_name="Classifier",
            content=CLASSIFIER_PROMPT,
        ),
        model=model,
    )
    # No tools - lightweight classification only
    # Returns structured output: {"type": "simple" | "complex", "reason": "..."}
```

System prompt: Analyzes user request complexity. Returns "simple" for direct Q&A, greetings, factual questions. Returns "complex" for multi-step tasks requiring tools, research, code, or document creation.

### Toolkits (CAMEL Built-in)

All toolkits are CAMEL's built-in implementations — no custom toolkit code needed. Toolkit events (activate/deactivate) are handled entirely through `ListenChatAgent._aexecute_tool()` overrides.

#### TerminalToolkit (`camel.toolkits.terminal_toolkit.TerminalToolkit`)
- `shell_exec(id, command, block=True)` - Execute shell commands (blocking/non-blocking)
- `shell_view(id)` - View output from non-blocking session
- `shell_write_to_process(id, command)` - Send input to running process
- `shell_kill_process(id)` - Terminate a running process
- Config: `safe_mode=True`, `clone_current_env=True`, `working_directory` per conversation

#### FileToolkit (`camel.toolkits.FileToolkit`)
- `write_to_file(filename, content, title, encoding, use_latex)` - Write Markdown, HTML, CSV, JSON, YAML, PDF, Word
- `read_file(file_paths)` - Read files with MarkItDown format conversion (supports PDF, Word, Excel, images via OCR, audio)
- `edit_file(file_path, old_content, new_content)` - Replace text in files
- `search_files(pattern, file_types, path)` - Search for patterns across files
- Config: `default_encoding="utf-8"`, `backup_enabled=True`, `working_directory` per conversation

#### NoteTakingToolkit (`camel.toolkits.NoteTakingToolkit`)
- `create_note(note_name, content, overwrite=False)` - Create markdown note
- `append_note(note_name, content)` - Append to existing note
- `read_note(note_name="all_notes")` - Read single or all notes
- `list_note()` - List all notes with file sizes
- Storage: Markdown files in `working_directory` with `.note_register` index
- Thread-safe with retry logic for concurrent access
- All agents in the same workforce share the same `working_directory`, so notes are automatically shared

## Chat Endpoint Flow (Refactored)

```python
# POST /api/chat
async def chat(request: ChatRequest, db=Depends(get_db)):
    # 1. Validate conversation exists
    if not await conversation_exists(db, request.conversation_id):
        raise HTTPException(404, "Conversation not found")

    # 2. Save user message to DB
    await add_message(db, request.conversation_id, "user", request.message)

    # 3. Load conversation history
    history = await get_messages(db, request.conversation_id)

    # 4. Build model config
    model = ModelFactory.create(
        model_platform=PLATFORM_MAP[request.provider],
        model_type=request.model,
        api_key=request.api_key,
        url=request.api_base,
        model_config_dict={"stream": True, "temperature": 0.7},
    )

    async def event_stream():
        task_lock = TaskLock(
            id=request.conversation_id,
            status=Status.classifying,
            queue=asyncio.Queue(),
        )

        try:
            # 5. Classify question
            classifier = create_classifier_agent(model)
            classification = await classify_question(classifier, request.message, history)

            if classification == "simple":
                # 6a. Simple path: direct streaming (adapted to new envelope format)
                agent = build_simple_agent(history, model)
                full_content = ""
                async for event in agent_chat(agent, request.message):
                    if event["type"] == "delta":
                        yield sse_json("delta", {"content": event["content"]})
                        full_content += event["content"]
                    elif event["type"] == "done":
                        full_content = event["content"]
                # Save and finalize
                await add_message(db, request.conversation_id, "assistant", full_content)
                conv = await get_conversation(db, request.conversation_id)
                yield sse_json("done", {"content": full_content, "conversation": conv})

            else:
                # 6b. Complex path: workforce
                workforce = build_workforce(task_lock, model)

                # Start workforce in background
                bg_task = asyncio.create_task(
                    workforce.run(request.message)
                )
                task_lock.background_tasks.add(bg_task)

                # Consume events from TaskLock queue
                while True:
                    # Check if background task crashed without emitting end/error
                    if bg_task.done() and task_lock.queue.empty():
                        exc = bg_task.exception()
                        if exc:
                            yield sse_json("error", {"message": str(exc)})
                        break

                    try:
                        event = await asyncio.wait_for(
                            task_lock.get_event(),
                            timeout=300,  # 5 minute timeout per event
                        )
                    except asyncio.TimeoutError:
                        yield sse_json("error", {"message": "Workforce timed out"})
                        break

                    # The end event from callback has no conversation data.
                    # Enrich it with conversation data and DB persistence.
                    if event["step"] == "end":
                        content = event["data"].get("content", "")
                        await add_message(db, request.conversation_id, "assistant", content)
                        conv = await get_conversation(db, request.conversation_id)
                        yield sse_json("end", {"content": content, "conversation": conv})
                        break
                    elif event["step"] == "error":
                        yield sse_json("error", event["data"])
                        break
                    else:
                        yield sse_json(event["step"], event["data"])

                # Wait for background task cleanup
                if not bg_task.done():
                    bg_task.cancel()
                    try:
                        await bg_task
                    except asyncio.CancelledError:
                        pass

        except Exception as e:
            yield sse_json("error", {"message": str(e)})
        finally:
            await task_lock.cleanup()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

### SSE Helper

```python
import json

def sse_json(step: str, data) -> str:
    """Serialize an SSE event to the wire format."""
    payload = {"step": step, "data": data}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
```

## Workforce Builder

```python
def build_workforce(task_lock: TaskLock, model: BaseModelBackend) -> CapeWorkforce:
    # Create a shared working directory for this session
    # All toolkits (terminal, file, notes) share this directory
    import tempfile
    working_dir = tempfile.mkdtemp(prefix=f"cape_{task_lock.id[:8]}_")
    task_lock.working_directory = working_dir

    # Create workforce (coordinator + task agents are created internally by CAMEL)
    workforce = CapeWorkforce(
        task_lock=task_lock,
        description="Cape Agent Workforce with browser, developer, and document agents",
    )

    # Add specialized workers
    # ListenChatAgent extends ChatAgent, so it's compatible with add_single_agent_worker
    if browser_service.connected:
        browser_agent = create_browser_agent(task_lock, model)
        workforce.add_single_agent_worker(
            description="Web research, browsing, and information gathering",
            worker=browser_agent,
        )

    developer_agent = create_developer_agent(task_lock, model, working_dir)
    workforce.add_single_agent_worker(
        description="Code writing, execution, and technical implementation",
        worker=developer_agent,
    )

    document_agent = create_document_agent(task_lock, model, working_dir)
    workforce.add_single_agent_worker(
        description="Document creation, file management, and content writing",
        worker=document_agent,
    )

    return workforce
```

## Frontend Changes

### Unified SSE Event Format

Both simple and complex paths use the same envelope:

```typescript
// Replaces old SSEEvent interface
interface SSEEvent {
  step: string;   // Event type
  data: any;      // Step-specific payload
}
```

The old `SSEEvent` with `type`/`content`/`tool_name`/`tool_args`/`tool_result`/`step_id` fields is removed.

### Extended Zustand Store

New state slice for task tracking (per conversation):

```typescript
// New types
interface SubTask {
  id: string;
  content: string;
  state: 'open' | 'waiting' | 'running' | 'done' | 'failed';  // All lowercase
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

### SSE Format Migration

The old SSE format `{"type": "delta", "content": "..."}` is replaced with `{"step": "delta", "data": {"content": "..."}}` across both paths. The frontend SSE parser is updated to use the new format. No backward compatibility shim is needed since both frontend and backend are updated together.

### Files Modified

| File | Change |
|------|--------|
| `backend/app/api/chat.py` | Major refactor: add classifier, TaskLock, workforce path |
| `backend/app/services/agent_service.py` | Simplify: remove CapeAgent class, keep build_simple_agent + agent_chat for simple path |
| `backend/app/models/schemas.py` | Add sse_json helper, remove old SSE event types |
| `frontend/src/renderer/services/api.ts` | Change SSEEvent format, switch to single onEvent callback |
| `frontend/src/renderer/stores/store.ts` | Add taskState slice, handleSSEEvent dispatcher |
| `frontend/src/renderer/hooks/useChat.ts` | Update to use new onEvent callback pattern |
| `frontend/src/renderer/components/chat/StreamingMessage.tsx` | Extend for workforce mode display |
| `frontend/src/renderer/types/index.ts` | Add SubTask, AgentActivity, extended types |

### Files Created

| File | Purpose |
|------|---------|
| `backend/app/models/enums.py` | Status enum |
| `backend/app/services/task_lock.py` | TaskLock class with asyncio.Queue and cleanup |
| `backend/app/agents/__init__.py` | Package init |
| `backend/app/agents/listen_chat_agent.py` | ChatAgent with SSE event streaming |
| `backend/app/agents/workforce.py` | CapeWorkforce + CapeWorkforceCallback |
| `backend/app/agents/single_agent_worker.py` | CapeAgentWorker bridge for task execution |
| `backend/app/agents/factory/__init__.py` | Package init |
| `backend/app/agents/factory/browser.py` | Browser agent factory |
| `backend/app/agents/factory/developer.py` | Developer agent factory |
| `backend/app/agents/factory/document.py` | Document agent factory |
| `backend/app/agents/factory/classifier.py` | Question classifier factory |
| `frontend/src/renderer/components/chat/TaskProgress.tsx` | Subtask progress display |
