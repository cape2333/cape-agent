# Task Decomposition & Context Injection Optimization

**Date**: 2026-03-29
**Scope**: Backend only (no frontend changes)
**Reference**: Eigent project best practices

## Problem

1. **Task decomposition prompt lacks key strategies**: Subtasks may contain implicit references to each other ("based on the previous step"), sequential operations for the same worker type aren't merged, and parallelization guidance is vague. The hard limit of 2-5 subtasks can be suboptimal for certain tasks.

2. **Workforce has no conversation context**: When a user sends multiple complex requests in the same conversation, the task decomposer and coordinator have zero knowledge of previous rounds. This causes redundant work and broken continuity (e.g., "write a report based on the research you just did" fails because the decomposer doesn't know what research was done).

## Design

### Change 1: Task Decomposer Prompt Optimization

**File**: `backend/app/services/agent_service.py` — `TASK_DECOMPOSER_PROMPT_TEMPLATE`

Replace the current `<decomposition_principles>` section with enhanced rules:

```
<decomposition_principles>
- **Self-contained subtasks**: Each subtask MUST be fully independent and
  understandable in isolation. Do NOT use relative references like "based on
  the previous step", "from the first task", or "using the above results".
  If a subtask needs upstream output, explicitly describe the required
  content (e.g., "Analyze the document titled 'React Framework Comparison'
  saved at {working_directory}/comparison.md").
- **Strategic grouping**: Sequential actions that require the same worker
  type SHOULD be grouped into a single subtask to reduce scheduling
  overhead. For example, "search for React info" + "search for Vue info"
  should be one Browser Agent subtask, not two.
- **Aggressive parallelization**: Different worker specializations MUST be
  split into separate subtasks to enable parallel execution. Multiple
  independent items of the same type SHOULD also be split into parallel
  subtasks when they don't share state.
- **Balanced granularity**: Each subtask should be large enough to be
  meaningful and small enough for effective parallelism. Avoid
  over-decomposition — splitting into too many tiny tasks adds overhead
  without benefit.
- Match subtasks to agent capabilities: research tasks for Browser Agent,
  coding tasks for Developer Agent, document tasks for Document Agent.
- Identify dependencies between subtasks and order them logically.
  Independent subtasks should be marked for parallel execution.
- NEVER ask agents to extract raw HTML or full page source code.
- NEVER create overly detailed extraction schemas.
- Focus on high-level goals: browse, summarize, write, code.
- Each subtask description should be self-contained with enough context
  for the assigned agent to work independently.
- When a subtask requires file output, specify the exact file path using
  the working directory (e.g., `{working_directory}/output.py`).
</decomposition_principles>
```

Key changes from current prompt:
- Added explicit self-contained constraint with examples of forbidden patterns
- Added strategic grouping rule for same-worker-type operations
- Added aggressive parallelization rule for different-worker-type operations
- Removed hard "2-5 subtasks" limit, replaced with "balanced granularity" principle
- Preserved all existing rules about file paths, HTML extraction, etc.

### Change 2: Multi-Round Context Injection

#### 2a. TaskLock — add conversation_history

**File**: `backend/app/services/task_lock.py`

Add a `conversation_history` field to `TaskLock`:

```python
@dataclass
class TaskLock:
    id: str
    status: Status
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    workforce: Optional[object] = None
    working_directory: str = ""
    background_tasks: set = field(default_factory=set)
    conversation_history: list = field(default_factory=list)  # NEW
```

Each entry in `conversation_history` is a dict:
```python
{
    "task_content": str,       # The user's original request for that round
    "task_result": str,        # Summary of what was accomplished
    "working_directory": str,  # Where files were saved
}
```

#### 2b. agent_service — build_conversation_context()

**File**: `backend/app/services/agent_service.py`

New function that formats conversation history for the decomposer:

```python
def build_conversation_context(task_lock: TaskLock) -> str:
    """Build structured context from previous workforce rounds."""
    if not task_lock.conversation_history:
        return ""

    parts = ["=== CONVERSATION HISTORY ==="]
    for i, entry in enumerate(task_lock.conversation_history, 1):
        parts.append(f"\n**Round {i}**")
        parts.append(f"Task: {entry['task_content']}")
        result = entry.get("task_result", "")
        if result:
            parts.append(f"Result: {result}")

    # Collect all generated files across rounds
    all_dirs = [
        e["working_directory"]
        for e in task_lock.conversation_history
        if e.get("working_directory")
    ]
    if all_dirs:
        files = []
        for d in all_dirs:
            dir_path = Path(d)
            if dir_path.exists():
                files.extend(str(f) for f in dir_path.rglob("*") if f.is_file())
        if files:
            parts.append(f"\nGenerated Files: {files}")

    return "\n".join(parts)
```

#### 2c. CapeWorkforce.run() — inject context into task content

**File**: `backend/app/agents/workforce.py`

Modify `run()` to temporarily prepend conversation context to the task content before decomposition, then restore after:

```python
async def run(self, question: str):
    task_content = question + DEFAULT_SUMMARY_PROMPT
    main_task = Task(content=task_content, id=f"main_{uuid4().hex[:8]}")
    self.task_lock.status = Status.decomposing

    # Inject conversation history context for the decomposer
    context = build_conversation_context(self.task_lock)
    if context:
        original_content = main_task.content
        main_task.content = (
            context
            + "\n\n=== CURRENT TASK ===\n"
            + original_content
        )

    try:
        self.task_lock.status = Status.executing
        result = await self.process_task_async(main_task)

        # Restore original content (avoid polluting task tree)
        if context:
            main_task.content = original_content

        return result
    except Exception as e:
        await self.task_lock.put_event("error", {
            "message": f"Workforce error: {str(e)}"
        })
        raise
```

#### 2d. chat.py — persist round results to conversation_history

**File**: `backend/app/api/chat.py`

Two changes:

1. **Persist TaskLock across rounds** in the same conversation (instead of creating a new one each time). Use a module-level dict to store active TaskLocks by conversation_id.

2. **After workforce completes**, append the round's structured result to `task_lock.conversation_history`.

```python
# Module-level registry of active task locks per conversation
_active_task_locks: dict[str, TaskLock] = {}

# In event_stream(), replace fresh TaskLock creation:
task_lock = _active_task_locks.get(req.conversation_id)
if task_lock is None:
    task_lock = TaskLock(id=req.conversation_id, status=Status.classifying)
    _active_task_locks[req.conversation_id] = task_lock
else:
    task_lock.status = Status.classifying
    task_lock.queue = asyncio.Queue()  # Fresh queue for this round

# After workforce "end" event, before yielding:
task_lock.conversation_history.append({
    "task_content": req.message,
    "task_result": content,  # The summarized result
    "working_directory": task_lock.working_directory,
})
```

**Cleanup**: When the SSE stream ends with an error or the conversation is deleted, remove the TaskLock from `_active_task_locks`.

### What is NOT changing

- Coordinator prompt (`COORDINATOR_PROMPT_TEMPLATE`) — no changes
- Assignment logic — no changes
- Frontend — no changes
- Streaming decomposition — not adding
- User editable subtasks — not adding
- Quality evaluation / retry logic — no changes

## File Change Summary

| File | Change |
|------|--------|
| `backend/app/services/agent_service.py` | Update `TASK_DECOMPOSER_PROMPT_TEMPLATE`; add `build_conversation_context()` |
| `backend/app/services/task_lock.py` | Add `conversation_history` field |
| `backend/app/agents/workforce.py` | Modify `run()` to inject/restore context; import `build_conversation_context` |
| `backend/app/api/chat.py` | Persist `TaskLock` across rounds; append results to `conversation_history` after completion |
