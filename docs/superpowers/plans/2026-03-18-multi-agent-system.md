# Multi-Agent System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor cape-agent from a single-agent to a multi-agent system with LLM routing, CAMEL Workforce orchestration, and real-time SSE status streaming.

**Architecture:** User messages are classified as simple (direct SSE streaming) or complex (Workforce decomposes into subtasks, assigns to browser/developer/document agents). All lifecycle events flow through a TaskLock queue to the SSE endpoint. Frontend displays task progress and agent activity.

**Tech Stack:** Python 3.10, FastAPI, CAMEL-AI 0.2.80 (Workforce, WorkforceCallback, ChatAgent, TerminalToolkit, FileToolkit, NoteTakingToolkit), React, TypeScript, Zustand, Tailwind CSS.

**Spec:** `docs/superpowers/specs/2026-03-18-multi-agent-system-design.md`

---

## File Map

### New Backend Files

| File | Responsibility |
|------|---------------|
| `backend/app/models/enums.py` | `Status` enum (classifying, decomposing, executing, done) |
| `backend/app/services/task_lock.py` | `TaskLock` dataclass with asyncio.Queue, cleanup logic |
| `backend/app/agents/__init__.py` | Package init |
| `backend/app/agents/listen_chat_agent.py` | `ListenChatAgent`: ChatAgent subclass emitting activate/deactivate agent + toolkit SSE events |
| `backend/app/agents/workforce.py` | `CapeWorkforceCallback` + `CapeWorkforce`: Workforce subclass with SSE callback |
| `backend/app/agents/single_agent_worker.py` | `CapeAgentWorker`: bridges Workforce task assignment to ListenChatAgent |
| `backend/app/agents/factory/__init__.py` | Package init |
| `backend/app/agents/factory/classifier.py` | `create_classifier_agent()` + `classify_question()` |
| `backend/app/agents/factory/browser.py` | `create_browser_agent()` with BROWSER_SYSTEM_PROMPT |
| `backend/app/agents/factory/developer.py` | `create_developer_agent()` with TerminalToolkit + NoteTakingToolkit |
| `backend/app/agents/factory/document.py` | `create_document_agent()` with FileToolkit + NoteTakingToolkit |

### New Frontend Files

| File | Responsibility |
|------|---------------|
| `frontend/src/renderer/components/chat/TaskProgress.tsx` | Subtask list with status indicators and progress bar |

### Modified Backend Files

| File | Change |
|------|--------|
| `backend/app/models/schemas.py` | Add `sse_json()` helper function |
| `backend/app/services/agent_service.py` | Remove `CapeAgent` class, keep `build_agent`/`agent_chat` for simple path, add `build_workforce` |
| `backend/app/api/chat.py` | Major refactor: classifier routing, TaskLock queue loop, workforce path |

### Modified Frontend Files

| File | Change |
|------|--------|
| `frontend/src/renderer/types/index.ts` | Add `SubTask`, `AgentActivity`, `TaskState` types; update `SSEEvent` |
| `frontend/src/renderer/services/api.ts` | New `SSEEvent` format `{step, data}`, single `onEvent` callback |
| `frontend/src/renderer/stores/store.ts` | Add `taskStates` slice with handleSSEEvent dispatcher |
| `frontend/src/renderer/hooks/useChat.ts` | Use new `onEvent` pattern, expose `taskState` |
| `frontend/src/renderer/components/chat/StreamingMessage.tsx` | Render TaskProgress and decomposition text in workforce mode |

---

## Task 1: Status Enum + TaskLock

**Files:**
- Create: `backend/app/models/enums.py`
- Create: `backend/app/services/task_lock.py`

- [ ] **Step 1: Create enums.py**

```python
# backend/app/models/enums.py
from enum import Enum


class Status(str, Enum):
    classifying = "classifying"
    decomposing = "decomposing"
    executing = "executing"
    done = "done"
```

- [ ] **Step 2: Create task_lock.py**

```python
# backend/app/services/task_lock.py
import asyncio
from dataclasses import dataclass, field
from typing import Optional

from app.models.enums import Status


@dataclass
class TaskLock:
    id: str
    status: Status
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    workforce: Optional[object] = None
    working_directory: str = ""
    background_tasks: set = field(default_factory=set)

    async def put_event(self, step: str, data: dict):
        await self.queue.put({"step": step, "data": data})

    async def get_event(self) -> dict:
        return await self.queue.get()

    async def cleanup(self):
        if self.workforce and hasattr(self.workforce, "stop"):
            self.workforce.stop()
        for task in self.background_tasks:
            task.cancel()
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
```

- [ ] **Step 3: Add sse_json to schemas.py**

Add to the end of `backend/app/models/schemas.py`:

```python
import json


def sse_json(step: str, data) -> str:
    payload = {"step": step, "data": data}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/enums.py backend/app/services/task_lock.py backend/app/models/schemas.py
git commit -m "feat: add Status enum, TaskLock, and sse_json helper"
```

---

## Task 2: ListenChatAgent

**Files:**
- Create: `backend/app/agents/__init__.py`
- Create: `backend/app/agents/listen_chat_agent.py`

- [ ] **Step 1: Create package init**

```python
# backend/app/agents/__init__.py
```

- [ ] **Step 2: Create listen_chat_agent.py**

```python
# backend/app/agents/listen_chat_agent.py
import json
import logging
from typing import Any, Dict, Optional
from uuid import uuid4

from camel.agents import ChatAgent
from camel.agents._types import ToolCallRequest
from camel.toolkits import FunctionTool

from app.services.task_lock import TaskLock

logger = logging.getLogger(__name__)


class ListenChatAgent(ChatAgent):
    """ChatAgent that emits SSE events for agent activation and tool execution."""

    def __init__(self, task_lock: TaskLock, agent_name: str, **kwargs):
        super().__init__(**kwargs)
        self.task_lock = task_lock
        self.agent_name = agent_name
        self.agent_id = f"{agent_name.lower().replace(' ', '_')}_{uuid4().hex[:8]}"
        self.process_task_id: str = ""

    async def astep(self, input_message, **kwargs):
        await self.task_lock.put_event("activate_agent", {
            "agent_name": self.agent_name,
            "agent_id": self.agent_id,
            "process_task_id": self.process_task_id,
            "message": "",
        })

        try:
            response = await super().astep(input_message, **kwargs)

            final_message = ""
            if hasattr(response, "msg") and response.msg:
                final_message = response.msg.content or ""

            await self.task_lock.put_event("deactivate_agent", {
                "agent_name": self.agent_name,
                "agent_id": self.agent_id,
                "process_task_id": self.process_task_id,
                "message": final_message,
            })
            return response

        except Exception as e:
            await self.task_lock.put_event("deactivate_agent", {
                "agent_name": self.agent_name,
                "agent_id": self.agent_id,
                "process_task_id": self.process_task_id,
                "message": f"Error: {str(e)}",
            })
            raise

    async def _aexecute_tool(self, tool_call_request: ToolCallRequest):
        tool_name = tool_call_request.tool_name
        toolkit_name = self._resolve_toolkit_name(tool_name)
        tool_args = str(tool_call_request.args)[:200]

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

    async def _aexecute_tool_from_stream_data(
        self, tool_call_data: Dict[str, Any]
    ):
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
        return tool_name.split("_")[0] if "_" in tool_name else tool_name
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/agents/
git commit -m "feat: add ListenChatAgent with SSE event streaming"
```

---

## Task 3: CapeWorkforceCallback + CapeWorkforce

**Files:**
- Create: `backend/app/agents/workforce.py`

- [ ] **Step 1: Create workforce.py**

```python
# backend/app/agents/workforce.py
import asyncio
import logging
from uuid import uuid4

from camel.societies.workforce import Workforce
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
from camel.tasks import Task

from app.models.enums import Status
from app.services.task_lock import TaskLock

logger = logging.getLogger(__name__)


class CapeWorkforceCallback(WorkforceCallback):
    """Translates CAMEL Workforce lifecycle events into SSE events."""

    def __init__(self, task_lock: TaskLock):
        self.task_lock = task_lock
        self._loop = asyncio.get_event_loop()

    def _emit(self, step: str, data: dict):
        asyncio.run_coroutine_threadsafe(
            self.task_lock.put_event(step, data),
            self._loop,
        )

    def log_task_created(self, event: TaskCreatedEvent) -> None:
        pass

    def log_task_decomposed(self, event: TaskDecomposedEvent) -> None:
        self._emit("decompose_progress", {
            "sub_tasks": [
                {"id": t.id, "content": t.content, "state": "open"}
                for t in event.subtasks
            ],
            "is_final": True,
        })

    def log_task_assigned(self, event: TaskAssignedEvent) -> None:
        self._emit("assign_task", {
            "task_id": event.task_id,
            "assignee_id": getattr(event, "worker_description", None)
                or getattr(event, "assignee_id", "unknown"),
            "content": getattr(event, "task_content", ""),
            "state": "waiting",
        })

    def log_task_started(self, event: TaskStartedEvent) -> None:
        self._emit("assign_task", {
            "task_id": event.task_id,
            "assignee_id": getattr(event, "worker_description", None)
                or getattr(event, "assignee_id", "unknown"),
            "content": getattr(event, "task_content", ""),
            "state": "running",
        })

    def log_task_completed(self, event: TaskCompletedEvent) -> None:
        self._emit("task_state", {
            "task_id": event.task_id,
            "state": "done",
            "result": getattr(event, "result", ""),
            "content": getattr(event, "task_content", ""),
        })

    def log_task_failed(self, event: TaskFailedEvent) -> None:
        self._emit("task_state", {
            "task_id": event.task_id,
            "state": "failed",
            "result": str(getattr(event, "error", "")),
            "content": getattr(event, "task_content", ""),
        })

    def log_worker_created(self, event: WorkerCreatedEvent) -> None:
        pass

    def log_worker_deleted(self, event: WorkerDeletedEvent) -> None:
        pass

    def log_all_tasks_completed(self, event: AllTasksCompletedEvent) -> None:
        results = []
        for tr in getattr(event, "task_results", []):
            results.append(f"- {tr.content}: {tr.result}")
        summary = "\n".join(results) if results else "Task completed."
        self._emit("end", {"content": summary})


class CapeWorkforce(Workforce):
    """Workforce with SSE event streaming via callback."""

    def __init__(self, task_lock: TaskLock, **kwargs):
        callback = CapeWorkforceCallback(task_lock)
        super().__init__(callbacks=[callback], **kwargs)
        self.task_lock = task_lock

    async def run(self, question: str):
        main_task = Task(content=question, id=f"main_{uuid4().hex[:8]}")
        self.task_lock.status = Status.decomposing

        try:
            self.task_lock.status = Status.executing
            result = await self.process_task_async(main_task)
            return result
        except Exception as e:
            await self.task_lock.put_event("error", {
                "message": f"Workforce error: {str(e)}"
            })
            raise
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/agents/workforce.py
git commit -m "feat: add CapeWorkforce with WorkforceCallback for SSE events"
```

---

## Task 4: CapeAgentWorker

**Files:**
- Create: `backend/app/agents/single_agent_worker.py`

- [ ] **Step 1: Create single_agent_worker.py**

```python
# backend/app/agents/single_agent_worker.py
import logging
from typing import List

from camel.societies.workforce import SingleAgentWorker
from camel.tasks import Task, TaskState

from app.agents.listen_chat_agent import ListenChatAgent

logger = logging.getLogger(__name__)

PROCESS_TASK_PROMPT = """You are assigned the following task:

**Task:** {content}

**Parent Task Context:** {parent_task_content}

**Dependency Results:**
{dependency_tasks_info}

Complete this task thoroughly. When done, provide your result as a clear,
actionable summary of what was accomplished."""


class CapeAgentWorker(SingleAgentWorker):
    """Worker that sets process_task_id for SSE event correlation."""

    def __init__(self, description: str, worker: ListenChatAgent, **kwargs):
        super().__init__(description=description, worker=worker, **kwargs)
        self._cape_worker = worker

    async def _process_task(
        self, task: Task, dependencies: List[Task]
    ) -> TaskState:
        self._cape_worker.process_task_id = task.id

        dep_info = self._format_dependencies(dependencies)
        parent_content = task.parent.content if task.parent else "N/A"

        prompt = PROCESS_TASK_PROMPT.format(
            content=task.content,
            parent_task_content=parent_content,
            dependency_tasks_info=dep_info if dep_info else "None",
        )

        try:
            response = await self._cape_worker.astep(prompt)

            response_content = ""
            if hasattr(response, "msg") and response.msg:
                response_content = response.msg.content or ""

            task.result = response_content
            return TaskState.DONE

        except Exception as e:
            logger.error(f"Task {task.id} failed: {e}", exc_info=True)
            task.result = f"Failed: {str(e)}"
            return TaskState.FAILED

    def _format_dependencies(self, dependencies: List[Task]) -> str:
        if not dependencies:
            return ""
        lines = []
        for dep in dependencies:
            result = dep.result if dep.result else "No result"
            lines.append(f"- [{dep.id}] {dep.content}: {result}")
        return "\n".join(lines)
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/agents/single_agent_worker.py
git commit -m "feat: add CapeAgentWorker for task-agent bridging"
```

---

## Task 5: Agent Factories

**Files:**
- Create: `backend/app/agents/factory/__init__.py`
- Create: `backend/app/agents/factory/classifier.py`
- Create: `backend/app/agents/factory/browser.py`
- Create: `backend/app/agents/factory/developer.py`
- Create: `backend/app/agents/factory/document.py`

- [ ] **Step 1: Create factory package init**

```python
# backend/app/agents/factory/__init__.py
from .classifier import create_classifier_agent, classify_question
from .browser import create_browser_agent
from .developer import create_developer_agent
from .document import create_document_agent
```

- [ ] **Step 2: Create classifier.py**

```python
# backend/app/agents/factory/classifier.py
import json
import logging

from camel.agents import ChatAgent
from camel.messages import BaseMessage

logger = logging.getLogger(__name__)

CLASSIFIER_PROMPT = """\
You are a question classifier. Analyze the user's message and determine if it \
is a SIMPLE question or a COMPLEX task.

SIMPLE: Direct Q&A, greetings, factual questions, opinion requests, \
explanations, translations, math calculations. These can be answered \
directly without tools.

COMPLEX: Multi-step tasks requiring web browsing, code execution, \
file creation, research across multiple sources, document generation, \
or any task that benefits from specialized agents working together.

Respond with ONLY a JSON object:
{"type": "simple", "reason": "brief reason"}
or
{"type": "complex", "reason": "brief reason"}
"""


def create_classifier_agent(model) -> ChatAgent:
    return ChatAgent(
        system_message=BaseMessage.make_assistant_message(
            role_name="Classifier",
            content=CLASSIFIER_PROMPT,
        ),
        model=model,
    )


async def classify_question(
    agent: ChatAgent, message: str, history: list
) -> str:
    """Returns 'simple' or 'complex'."""
    try:
        response = await agent.astep(message)
        content = ""
        if hasattr(response, "msg") and response.msg:
            content = response.msg.content or ""

        # Parse JSON response
        # Strip markdown code fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = json.loads(content)
        classification = result.get("type", "simple")
        logger.info(
            f"Classification: {classification} - {result.get('reason', '')}"
        )
        return classification

    except Exception as e:
        logger.warning(f"Classification failed, defaulting to simple: {e}")
        return "simple"
```

- [ ] **Step 3: Create browser.py**

```python
# backend/app/agents/factory/browser.py
from camel.messages import BaseMessage
from camel.toolkits import NoteTakingToolkit

from app.agents.listen_chat_agent import ListenChatAgent
from app.services.browser_service import browser_service
from app.services.task_lock import TaskLock

BROWSER_SYSTEM_PROMPT = """\
You are a Senior Research Analyst. Your primary role is to conduct web \
research to gather, analyze, and document information.

You must use search/browser tools to get information — do not answer from \
your own knowledge.

After finding information, use note-taking tools to record your findings \
so other agents can access them.

Workflow:
1. Use browser_visit_page to navigate to relevant websites
2. Use browser_get_page_snapshot to understand page content
3. Interact with elements using browser_click, browser_type, browser_select
4. Record findings with create_note or append_note
5. Provide a comprehensive summary when done
"""


def create_browser_agent(
    task_lock: TaskLock, model, working_directory: str = ""
) -> ListenChatAgent:
    browser_tools = browser_service.get_tools()
    note_toolkit = NoteTakingToolkit(working_directory=working_directory)
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

- [ ] **Step 4: Create developer.py**

```python
# backend/app/agents/factory/developer.py
from camel.messages import BaseMessage
from camel.toolkits import NoteTakingToolkit
from camel.toolkits.terminal_toolkit import TerminalToolkit

from app.agents.listen_chat_agent import ListenChatAgent
from app.services.task_lock import TaskLock

DEVELOPER_SYSTEM_PROMPT = """\
You are a Lead Software Engineer. Your role is to solve technical tasks \
by writing and executing code, installing libraries, and interacting \
with the operating system.

You have full terminal access. Use shell_exec to run commands.

After creating files or producing results, use note-taking tools to \
register your work so other agents can access it.

Principles:
- Bias for action: execute code, don't just suggest it
- Verify your work by running and testing
- Keep the user informed with brief progress updates
"""


def create_developer_agent(
    task_lock: TaskLock, model, working_directory: str
) -> ListenChatAgent:
    terminal_toolkit = TerminalToolkit(
        working_directory=working_directory,
        safe_mode=True,
        clone_current_env=True,
        timeout=30.0,
    )
    note_toolkit = NoteTakingToolkit(working_directory=working_directory)
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

- [ ] **Step 5: Create document.py**

```python
# backend/app/agents/factory/document.py
from camel.messages import BaseMessage
from camel.toolkits import FileToolkit, NoteTakingToolkit

from app.agents.listen_chat_agent import ListenChatAgent
from app.services.task_lock import TaskLock

DOCUMENT_SYSTEM_PROMPT = """\
You are a Documentation Specialist. Your role is to create, modify, and \
manage documents in various formats.

Use write_to_file to create documents (Markdown, HTML, CSV, JSON, YAML). \
Use read_file to read existing documents. Use edit_file to modify them.

Before creating documents, use list_note and read_note to gather \
information from other agents. After creating documents, register them \
with append_note("shared_files", "- path: description").

Always use tools to create documents — never just output text as your response.
"""


def create_document_agent(
    task_lock: TaskLock, model, working_directory: str
) -> ListenChatAgent:
    file_toolkit = FileToolkit(
        working_directory=working_directory,
        default_encoding="utf-8",
        backup_enabled=True,
    )
    note_toolkit = NoteTakingToolkit(working_directory=working_directory)
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

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/factory/
git commit -m "feat: add agent factories (classifier, browser, developer, document)"
```

---

## Task 6: Refactor agent_service.py

**Files:**
- Modify: `backend/app/services/agent_service.py`

Keep `build_agent` and `agent_chat` for the simple path. Remove `CapeAgent` (replaced by `ListenChatAgent`). Add `build_workforce`.

- [ ] **Step 1: Rewrite agent_service.py**

Replace the entire file. Key changes:
- Remove `CapeAgent` class (moved to `ListenChatAgent`)
- Keep `PLATFORM_MAP`, `DEFAULT_SYSTEM_PROMPT`, `_make_message`, `build_agent`, `agent_chat` for simple path
- `build_agent` now uses plain `ChatAgent` (no tool tracking needed for simple path)
- Add `build_workforce` function

```python
# backend/app/services/agent_service.py
import json
import logging
import tempfile
from typing import AsyncGenerator, List, Optional

from camel.agents import ChatAgent
from camel.messages import BaseMessage
from camel.models import ModelFactory
from camel.toolkits import FunctionTool
from camel.types import ModelPlatformType, OpenAIBackendRole, RoleType

from app.agents.workforce import CapeWorkforce
from app.agents.factory import (
    create_browser_agent,
    create_developer_agent,
    create_document_agent,
)
from app.services.browser_service import browser_service
from app.services.task_lock import TaskLock

logger = logging.getLogger(__name__)

PLATFORM_MAP = {
    "openai": ModelPlatformType.OPENAI,
    "anthropic": ModelPlatformType.ANTHROPIC,
    "gemini": ModelPlatformType.GEMINI,
    "deepseek": ModelPlatformType.DEEPSEEK,
    "groq": ModelPlatformType.GROQ,
    "mistral": ModelPlatformType.MISTRAL,
    "ollama": ModelPlatformType.OLLAMA,
    "minimax": ModelPlatformType.MINIMAX,
}

DEFAULT_SYSTEM_PROMPT = "You are a helpful AI assistant."


def _make_message(role: str, content: str) -> BaseMessage:
    if role == "user":
        return BaseMessage(
            role_name="user", role_type=RoleType.USER,
            content=content, meta_dict={},
        )
    return BaseMessage(
        role_name="assistant", role_type=RoleType.ASSISTANT,
        content=content, meta_dict={},
    )


def build_model(
    provider: str,
    model_name: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
):
    """Create a CAMEL model backend."""
    platform = PLATFORM_MAP.get(provider, ModelPlatformType.OPENAI)
    kwargs = {}
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["url"] = api_base

    return ModelFactory.create(
        model_platform=platform,
        model_type=model_name,
        model_config_dict={"stream": True, "temperature": 0.7},
        **kwargs,
    )


def build_agent(
    provider: str,
    model_name: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    history: Optional[List[dict]] = None,
    tools: Optional[List[FunctionTool]] = None,
) -> ChatAgent:
    """Build a simple ChatAgent for the simple path (no workforce)."""
    model = build_model(provider, model_name, api_key, api_base)

    agent = ChatAgent(
        system_message=DEFAULT_SYSTEM_PROMPT,
        model=model,
        tools=tools or [],
    )

    if history:
        for msg in history:
            role_enum = (
                OpenAIBackendRole.USER
                if msg["role"] == "user"
                else OpenAIBackendRole.ASSISTANT
            )
            agent.update_memory(
                message=_make_message(msg["role"], msg["content"]),
                role=role_enum,
            )

    return agent


async def agent_chat(
    agent: ChatAgent,
    user_message: str,
) -> AsyncGenerator[dict, None]:
    """Simple path streaming. Yields {"type": "delta"/"done", ...} events."""
    response = await agent.astep(user_message)
    full_content = ""

    if hasattr(response, "__aiter__"):
        async for partial in response:
            delta = partial.msg.content if partial.msg else ""
            if delta:
                full_content += delta
                yield {"type": "delta", "content": delta}
    else:
        if response.msgs:
            full_content = response.msgs[0].content
            yield {"type": "delta", "content": full_content}

    yield {"type": "done", "content": full_content}


def build_workforce(
    task_lock: TaskLock,
    provider: str,
    model_name: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
) -> CapeWorkforce:
    """Build a CapeWorkforce with browser, developer, and document agents."""
    model = build_model(provider, model_name, api_key, api_base)

    working_dir = tempfile.mkdtemp(prefix=f"cape_{task_lock.id[:8]}_")
    task_lock.working_directory = working_dir

    workforce = CapeWorkforce(
        task_lock=task_lock,
        description="Cape Agent Workforce with browser, developer, and document agents",
    )

    if browser_service.connected:
        browser_agent = create_browser_agent(task_lock, model, working_dir)
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

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/agent_service.py
git commit -m "refactor: simplify agent_service, add build_workforce"
```

---

## Task 7: Refactor chat.py (Backend SSE Endpoint)

**Files:**
- Modify: `backend/app/api/chat.py`

- [ ] **Step 1: Rewrite chat.py with classifier + workforce routing**

```python
# backend/app/api/chat.py
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import aiosqlite

from app.models.database import get_db
from app.models.enums import Status
from app.models.schemas import ChatRequest, sse_json
from app.services.conversation_service import (
    get_messages,
    add_message,
    conversation_exists,
    get_conversation,
)
from app.services.agent_service import build_agent, agent_chat, build_workforce
from app.services.task_lock import TaskLock
from app.agents.factory import create_classifier_agent, classify_question
from app.services.agent_service import build_model

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.post("/chat")
async def chat(req: ChatRequest, db: aiosqlite.Connection = Depends(get_db)):
    if not await conversation_exists(db, req.conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    try:
        await add_message(db, req.conversation_id, "user", req.message)
    except aiosqlite.IntegrityError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc

    messages = await get_messages(db, req.conversation_id)
    history = [{"role": m.role, "content": m.content} for m in messages[:-1]]

    provider = req.provider or "openai"
    model_name = req.model or "gpt-4o-mini"

    logger.info(f"[CHAT] provider={provider}, model={model_name}")

    async def event_stream():
        task_lock = TaskLock(
            id=req.conversation_id,
            status=Status.classifying,
        )

        try:
            # Classify question
            model = build_model(provider, model_name, req.api_key, req.api_base)
            classifier = create_classifier_agent(model)
            classification = await classify_question(
                classifier, req.message, history
            )
            logger.info(f"[CHAT] classification={classification}")

            if classification == "simple":
                # Simple path: direct streaming
                agent = build_agent(
                    provider=provider,
                    model_name=model_name,
                    api_key=req.api_key,
                    api_base=req.api_base,
                    history=history,
                )
                full_content = ""
                async for event in agent_chat(agent, req.message):
                    if event["type"] == "delta":
                        yield sse_json("delta", {"content": event["content"]})
                        full_content += event["content"]
                    elif event["type"] == "done":
                        full_content = event.get("content", full_content)

                await add_message(
                    db, req.conversation_id, "assistant", full_content
                )
                conv = await get_conversation(db, req.conversation_id)
                yield sse_json("done", {
                    "content": full_content,
                    "conversation": conv.model_dump() if conv else None,
                })

            else:
                # Complex path: workforce
                workforce = build_workforce(
                    task_lock=task_lock,
                    provider=provider,
                    model_name=model_name,
                    api_key=req.api_key,
                    api_base=req.api_base,
                )

                bg_task = asyncio.create_task(workforce.run(req.message))
                task_lock.background_tasks.add(bg_task)

                while True:
                    if bg_task.done() and task_lock.queue.empty():
                        exc = bg_task.exception()
                        if exc:
                            yield sse_json("error", {"message": str(exc)})
                        break

                    try:
                        event = await asyncio.wait_for(
                            task_lock.get_event(), timeout=300
                        )
                    except asyncio.TimeoutError:
                        yield sse_json("error", {
                            "message": "Workforce timed out"
                        })
                        break

                    if event["step"] == "end":
                        content = event["data"].get("content", "")
                        await add_message(
                            db, req.conversation_id, "assistant", content
                        )
                        conv = await get_conversation(db, req.conversation_id)
                        yield sse_json("end", {
                            "content": content,
                            "conversation": conv.model_dump() if conv else None,
                        })
                        break
                    elif event["step"] == "error":
                        yield sse_json("error", event["data"])
                        break
                    else:
                        yield sse_json(event["step"], event["data"])

                if not bg_task.done():
                    bg_task.cancel()
                    try:
                        await bg_task
                    except asyncio.CancelledError:
                        pass

        except Exception as e:
            logger.error(f"Chat error: {e}", exc_info=True)
            error_msg = str(e)
            if "API" in error_msg and "key" in error_msg.lower():
                error_msg = "API key is missing. Please configure it in Settings."
            yield sse_json("error", {"message": error_msg})
        finally:
            await task_lock.cleanup()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

- [ ] **Step 2: Verify backend starts**

Run: `cd /Users/didi/Documents/opensource/cape-agent/backend && python -c "from app.api.chat import router; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/chat.py
git commit -m "refactor: chat endpoint with classifier routing and workforce path"
```

---

## Task 8: Frontend Types

**Files:**
- Modify: `frontend/src/renderer/types/index.ts`

- [ ] **Step 1: Update types/index.ts**

Replace the `SSEEvent` and `AgentStep` interfaces. Add new types.

Add after the `ChatRequest` interface (line 36):

```typescript
// Multi-agent task tracking
export interface SubTask {
  id: string;
  content: string;
  state: 'open' | 'waiting' | 'running' | 'done' | 'failed';
  assigneeId?: string;
  result?: string;
}

export interface AgentActivity {
  agentId: string;
  agentName: string;
  processTaskId: string;
  message: string;
}

export interface TaskStateInfo {
  status: 'idle' | 'classifying' | 'decomposing' | 'executing' | 'done';
  subTasks: SubTask[];
  activeAgents: AgentActivity[];
  streamingDecomposeText: string;
}
```

Replace the existing `SSEEvent` interface (lines 48-58) with:

```typescript
export interface SSEEvent {
  step: string;
  data: Record<string, unknown>;
}
```

Keep the existing `AgentStep` interface unchanged (it's reused for toolkit events).

- [ ] **Step 2: Commit**

```bash
git add frontend/src/renderer/types/index.ts
git commit -m "feat: add multi-agent types (SubTask, AgentActivity, TaskStateInfo, new SSEEvent)"
```

---

## Task 9: Frontend SSE Handler (api.ts)

**Files:**
- Modify: `frontend/src/renderer/services/api.ts`

- [ ] **Step 1: Update sendChatMessage to use unified onEvent callback**

Replace the `ChatEventHandlers` interface and `sendChatMessage` function (lines 100-174) with:

```typescript
export async function sendChatMessage(
  req: ChatRequest,
  onEvent: (event: SSEEvent) => void,
): Promise<void> {
  await ensureApiUrl();
  const res = await fetch(`${BASE_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    onEvent({ step: "error", data: { message: `HTTP ${res.status}: ${res.statusText}` } });
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) {
    onEvent({ step: "error", data: { message: "No response body" } });
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
        onEvent(event);
      } catch {
        // skip malformed SSE
      }
    }
  }
}
```

Also remove the `ChatEventHandlers` export interface since it's no longer used.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/renderer/services/api.ts
git commit -m "refactor: unified SSE event handler with onEvent callback"
```

---

## Task 10: Zustand Store — taskStates Slice + handleSSEEvent

**Files:**
- Modify: `frontend/src/renderer/stores/store.ts`

- [ ] **Step 1: Add taskStates to store interface and implementation**

Add to the `AppState` interface (after agentSteps section, before closing brace):

```typescript
  // Task states (per-conversation, for workforce mode)
  taskStates: Record<string, TaskStateInfo>;
  handleSSEEvent: (conversationId: string, event: SSEEvent) => void;
  resetTaskState: (conversationId: string) => void;
```

Add the import at the top:

```typescript
import type { Conversation, Message, AppSettings, AgentStep, SSEEvent, TaskStateInfo, SubTask, AgentActivity } from "../types";
```

Add implementation inside `create<AppState>((set) => ({`:

```typescript
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
          streamingDecomposeText: '',
        },
      },
    })),

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
                ...(s.taskStates[conversationId] || { subTasks: [], activeAgents: [], streamingDecomposeText: '' }),
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
            status: 'decomposing', subTasks: [], activeAgents: [], streamingDecomposeText: '',
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
            status: 'decomposing', subTasks: [], activeAgents: [], streamingDecomposeText: '',
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
            status: 'executing', subTasks: [], activeAgents: [], streamingDecomposeText: '',
          };
          return {
            taskStates: {
              ...s.taskStates,
              [conversationId]: {
                ...ts3,
                status: 'executing',
                subTasks: ts3.subTasks.map(t =>
                  t.id === data.task_id
                    ? { ...t, state: data.state as SubTask['state'], assigneeId: data.assignee_id as string }
                    : t
                ),
              },
            },
          };
        }

        case 'activate_agent': {
          const ts4 = s.taskStates[conversationId] || {
            status: 'executing', subTasks: [], activeAgents: [], streamingDecomposeText: '',
          };
          const newAgent: AgentActivity = {
            agentId: data.agent_id as string,
            agentName: data.agent_name as string,
            processTaskId: data.process_task_id as string,
            message: '',
          };
          return {
            taskStates: {
              ...s.taskStates,
              [conversationId]: {
                ...ts4,
                activeAgents: [...ts4.activeAgents, newAgent],
              },
            },
          };
        }

        case 'deactivate_agent': {
          const ts5 = s.taskStates[conversationId] || {
            status: 'executing', subTasks: [], activeAgents: [], streamingDecomposeText: '',
          };
          return {
            taskStates: {
              ...s.taskStates,
              [conversationId]: {
                ...ts5,
                activeAgents: ts5.activeAgents.filter(
                  a => a.agentId !== data.agent_id
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
            status: 'executing', subTasks: [], activeAgents: [], streamingDecomposeText: '',
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
                ...(s.taskStates[conversationId] || { subTasks: [], activeAgents: [], streamingDecomposeText: '' }),
                status: 'done',
              },
            },
          };
        }

        default:
          return {};
      }
    }),
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/renderer/stores/store.ts
git commit -m "feat: add taskStates slice and handleSSEEvent dispatcher"
```

---

## Task 11: Update useChat Hook

**Files:**
- Modify: `frontend/src/renderer/hooks/useChat.ts`

- [ ] **Step 1: Rewrite useChat.ts**

```typescript
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
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/renderer/hooks/useChat.ts
git commit -m "refactor: useChat with unified SSE event handler"
```

---

## Task 12: TaskProgress Component

**Files:**
- Create: `frontend/src/renderer/components/chat/TaskProgress.tsx`

- [ ] **Step 1: Create TaskProgress.tsx**

```tsx
import React from "react";
import { Loader2, CheckCircle, XCircle, Clock, ListTodo } from "lucide-react";
import type { SubTask } from "../../types";

interface Props {
  subTasks: SubTask[];
}

const stateIcon: Record<string, React.ReactNode> = {
  open: <Clock size={12} className="text-warm-400" />,
  waiting: <Clock size={12} className="text-yellow-500" />,
  running: <Loader2 size={12} className="text-accent-500 animate-spin" />,
  done: <CheckCircle size={12} className="text-green-500" />,
  failed: <XCircle size={12} className="text-red-500" />,
};

const TaskProgress: React.FC<Props> = ({ subTasks }) => {
  if (!subTasks.length) return null;

  const completed = subTasks.filter(
    (t) => t.state === "done" || t.state === "failed"
  ).length;
  const progress = Math.round((completed / subTasks.length) * 100);

  return (
    <div className="mb-3">
      <div className="flex items-center gap-2 mb-2">
        <ListTodo size={14} className="text-warm-500" />
        <span className="text-xs font-medium text-warm-600">
          Tasks ({completed}/{subTasks.length})
        </span>
        <div className="flex-1 h-1.5 bg-warm-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-accent-500 rounded-full transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
      <div className="space-y-1">
        {subTasks.map((task) => (
          <div key={task.id} className="flex items-start gap-2 text-xs">
            <div className="flex-shrink-0 mt-0.5">
              {stateIcon[task.state] || stateIcon.open}
            </div>
            <div className="min-w-0">
              <span className="text-warm-600">{task.content}</span>
              {task.assigneeId && (
                <span className="text-warm-400 ml-1">
                  [{task.assigneeId}]
                </span>
              )}
              {task.result && task.state === "done" && (
                <div className="text-warm-400 mt-0.5 truncate">
                  {task.result}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default TaskProgress;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/renderer/components/chat/TaskProgress.tsx
git commit -m "feat: add TaskProgress component for subtask display"
```

---

## Task 13: Update StreamingMessage for Workforce Mode

**Files:**
- Modify: `frontend/src/renderer/components/chat/StreamingMessage.tsx`

- [ ] **Step 1: Update StreamingMessage.tsx**

Add workforce-mode rendering (decomposition text + task progress). Update Props and imports.

```tsx
import React from "react";
import ReactMarkdown from "react-markdown";
import { Loader2, CheckCircle, Globe, Brain } from "lucide-react";
import type { AgentStep, TaskStateInfo } from "../../types";
import TaskProgress from "./TaskProgress";

interface Props {
  content: string;
  agentSteps?: AgentStep[];
  taskState?: TaskStateInfo | null;
}

const AgentStepItem: React.FC<{ step: AgentStep }> = ({ step }) => {
  const isRunning = step.status === "running";

  return (
    <div className="flex items-start gap-2 py-1.5 text-xs">
      <div className="flex-shrink-0 mt-0.5">
        {isRunning ? (
          <Loader2 size={12} className="text-accent-500 animate-spin" />
        ) : (
          <CheckCircle size={12} className="text-green-500" />
        )}
      </div>
      <div className="min-w-0">
        <span className="font-medium text-warm-600">
          <Globe size={10} className="inline mr-1" />
          {step.toolName}
        </span>
        {step.toolArgs && Object.keys(step.toolArgs).length > 0 && (
          <span className="text-warm-400 ml-1">
            ({Object.entries(step.toolArgs).map(([k, v]) =>
              `${k}: ${typeof v === 'string' ? v.slice(0, 50) : JSON.stringify(v).slice(0, 50)}`
            ).join(", ")})
          </span>
        )}
        {step.result && (
          <div className="text-warm-400 mt-0.5 truncate">{step.result}</div>
        )}
      </div>
    </div>
  );
};

const StreamingMessage: React.FC<Props> = ({ content, agentSteps, taskState }) => {
  const hasSteps = agentSteps && agentSteps.length > 0;
  const isWorkforceMode = taskState && taskState.status !== "idle";
  const isDecomposing = taskState?.status === "decomposing";

  if (!content && !hasSteps && !isWorkforceMode) {
    return (
      <div className="flex px-4 py-2">
        <div className="bg-white px-4 py-3 rounded-2xl rounded-bl-md shadow-sm border border-warm-200">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium animate-shimmer">Analyzing your request...</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex px-4 py-2">
      <div className="max-w-[85%] bg-white px-4 py-3 rounded-2xl rounded-bl-md shadow-sm border border-warm-200">

        {/* Decomposition streaming text */}
        {isDecomposing && taskState.streamingDecomposeText && (
          <div className="mb-2 pb-2 border-b border-warm-100">
            <div className="flex items-center gap-1.5 mb-1">
              <Brain size={12} className="text-accent-500" />
              <span className="text-xs font-medium text-warm-500">Decomposing task...</span>
            </div>
            <div className="text-xs text-warm-400 whitespace-pre-wrap">
              {taskState.streamingDecomposeText}
            </div>
          </div>
        )}

        {/* Task progress (subtasks) */}
        {isWorkforceMode && taskState.subTasks.length > 0 && (
          <div className="mb-2 pb-2 border-b border-warm-100">
            <TaskProgress subTasks={taskState.subTasks} />
          </div>
        )}

        {/* Agent steps (tool calls) */}
        {hasSteps && (
          <div className="mb-2 pb-2 border-b border-warm-100">
            {agentSteps!.map((step) => (
              <AgentStepItem key={step.id} step={step} />
            ))}
          </div>
        )}

        {/* Text content */}
        {content && (
          <div className="prose prose-warm prose-sm max-w-none text-warm-700">
            <ReactMarkdown>{content}</ReactMarkdown>
            <span className="inline-block w-1.5 h-4 bg-accent-500 animate-pulse ml-0.5 align-text-bottom rounded-sm" />
          </div>
        )}

        {/* Loading states */}
        {!content && !hasSteps && isWorkforceMode && (
          <div className="flex items-center gap-2">
            <Loader2 size={14} className="text-accent-500 animate-spin" />
            <span className="text-sm text-warm-400">
              {isDecomposing ? "Decomposing task..." : "Agents working..."}
            </span>
          </div>
        )}
        {!content && hasSteps && !isWorkforceMode && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-warm-400 animate-shimmer">Working...</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default StreamingMessage;
```

- [ ] **Step 2: Update ChatArea.tsx to pass taskState to StreamingMessage**

Find where `StreamingMessage` is used in `ChatArea.tsx` and add the `taskState` prop. The exact change depends on how `ChatArea` is structured, but it should look like:

```tsx
<StreamingMessage
  content={streamingContent}
  agentSteps={agentSteps}
  taskState={taskState}
/>
```

Where `taskState` comes from `useChat()`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/renderer/components/chat/StreamingMessage.tsx frontend/src/renderer/components/chat/TaskProgress.tsx frontend/src/renderer/components/chat/ChatArea.tsx
git commit -m "feat: StreamingMessage with workforce mode (decomposition + task progress)"
```

---

## Task 14: Integration Test

- [ ] **Step 1: Start the backend and verify it runs**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
python main.py
```

Expected: Backend starts without import errors.

- [ ] **Step 2: Start the frontend and verify it builds**

```bash
cd /Users/didi/Documents/opensource/cape-agent/frontend
npm run dev
```

Expected: Frontend compiles without TypeScript errors.

- [ ] **Step 3: Send a simple message and verify SSE format**

Send a message like "Hello" and check:
- Classifier returns "simple"
- SSE events use new `{"step": "delta", "data": {...}}` format
- Response streams correctly

- [ ] **Step 4: Send a complex message and verify workforce**

Send a message like "Write a Python script that prints fibonacci numbers and save it to a file" and check:
- Classifier returns "complex"
- `decompose_progress` event arrives with subtask list
- `assign_task`, `activate_agent`, `deactivate_agent` events fire
- `task_state` events update subtask status
- `end` event fires with final summary
- TaskProgress component renders in the UI

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: multi-agent system MVP complete"
```
