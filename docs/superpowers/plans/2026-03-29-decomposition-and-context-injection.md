# Task Decomposition & Context Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve task decomposition quality and enable multi-round conversation context for the workforce decomposer.

**Architecture:** Two independent changes: (1) rewrite the decomposer prompt with stronger subtask independence, grouping, and parallelization rules; (2) add a conversation history accumulator in TaskLock, a context builder function, and inject context into the workforce run loop. Both changes are backend-only.

**Tech Stack:** Python 3.10, FastAPI, CAMEL-AI, pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/app/services/task_lock.py` | Modify | Add `conversation_history` field |
| `backend/app/services/agent_service.py` | Modify | Update decomposer prompt; add `build_conversation_context()` |
| `backend/app/agents/workforce.py` | Modify | Inject context in `run()`; restore after decomposition |
| `backend/app/api/chat.py` | Modify | Persist TaskLock across rounds; append results to history |
| `backend/tests/test_conversation_context.py` | Create | Tests for `build_conversation_context()` |

---

### Task 1: Set Up Test Infrastructure

**Files:**
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_conversation_context.py`

- [ ] **Step 1: Create tests directory and empty init**

```bash
mkdir -p /Users/didi/Documents/opensource/cape-agent/backend/tests
touch /Users/didi/Documents/opensource/cape-agent/backend/tests/__init__.py
```

- [ ] **Step 2: Install pytest in the backend venv**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
source workspace/.venv/bin/activate
pip install pytest
```

- [ ] **Step 3: Write the initial test file with tests for build_conversation_context**

Write `backend/tests/test_conversation_context.py`:

```python
"""Tests for build_conversation_context()."""

import os
import tempfile

from app.models.enums import Status
from app.services.task_lock import TaskLock
from app.services.agent_service import build_conversation_context


class TestBuildConversationContext:
    """Tests for build_conversation_context()."""

    def test_empty_history_returns_empty_string(self):
        task_lock = TaskLock(id="conv-1", status=Status.classifying)
        result = build_conversation_context(task_lock)
        assert result == ""

    def test_single_round_formats_correctly(self):
        task_lock = TaskLock(id="conv-1", status=Status.classifying)
        task_lock.conversation_history.append({
            "task_content": "Research React frameworks",
            "task_result": "Found React, Vue, and Angular as top 3.",
            "working_directory": "/tmp/test-workspace",
        })
        result = build_conversation_context(task_lock)
        assert "=== CONVERSATION HISTORY ===" in result
        assert "Round 1" in result
        assert "Research React frameworks" in result
        assert "Found React, Vue, and Angular as top 3." in result

    def test_multiple_rounds_all_included(self):
        task_lock = TaskLock(id="conv-1", status=Status.classifying)
        task_lock.conversation_history.append({
            "task_content": "Research React",
            "task_result": "React is a UI library.",
            "working_directory": "/tmp/ws1",
        })
        task_lock.conversation_history.append({
            "task_content": "Write comparison doc",
            "task_result": "Document saved to /tmp/ws2/comparison.md",
            "working_directory": "/tmp/ws2",
        })
        result = build_conversation_context(task_lock)
        assert "Round 1" in result
        assert "Round 2" in result
        assert "Research React" in result
        assert "Write comparison doc" in result

    def test_generated_files_listed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake file in the workspace
            test_file = os.path.join(tmpdir, "output.md")
            with open(test_file, "w") as f:
                f.write("test")

            task_lock = TaskLock(id="conv-1", status=Status.classifying)
            task_lock.conversation_history.append({
                "task_content": "Generate report",
                "task_result": "Report generated.",
                "working_directory": tmpdir,
            })
            result = build_conversation_context(task_lock)
            assert "Generated Files:" in result
            assert "output.md" in result

    def test_missing_working_directory_skipped(self):
        task_lock = TaskLock(id="conv-1", status=Status.classifying)
        task_lock.conversation_history.append({
            "task_content": "Some task",
            "task_result": "Done.",
            "working_directory": "/nonexistent/path/abc123",
        })
        result = build_conversation_context(task_lock)
        assert "=== CONVERSATION HISTORY ===" in result
        # Should not crash, just no files listed
        assert "Generated Files:" not in result

    def test_empty_task_result_omitted(self):
        task_lock = TaskLock(id="conv-1", status=Status.classifying)
        task_lock.conversation_history.append({
            "task_content": "Some task",
            "task_result": "",
            "working_directory": "",
        })
        result = build_conversation_context(task_lock)
        assert "Result:" not in result
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
source workspace/.venv/bin/activate
PYTHONPATH=. python -m pytest tests/test_conversation_context.py -v
```

Expected: FAIL with `ImportError: cannot import name 'build_conversation_context'`

- [ ] **Step 5: Commit test scaffold**

```bash
git add backend/tests/__init__.py backend/tests/test_conversation_context.py
git commit -m "test: add tests for build_conversation_context (red phase)"
```

---

### Task 2: Add conversation_history to TaskLock

**Files:**
- Modify: `backend/app/services/task_lock.py`

- [ ] **Step 1: Add conversation_history field to TaskLock**

In `backend/app/services/task_lock.py`, add the field to the dataclass:

```python
@dataclass
class TaskLock:
    id: str
    status: Status
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    workforce: Optional[object] = None
    working_directory: str = ""
    background_tasks: set = field(default_factory=set)
    conversation_history: list = field(default_factory=list)
```

This is a new `list` field with default empty list. Each entry will be a dict:
```python
{"task_content": str, "task_result": str, "working_directory": str}
```

- [ ] **Step 2: Verify no import errors**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
source workspace/.venv/bin/activate
PYTHONPATH=. python -c "from app.services.task_lock import TaskLock; tl = TaskLock(id='test', status='classifying'); print(tl.conversation_history)"
```

Expected: `[]`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/task_lock.py
git commit -m "feat: add conversation_history field to TaskLock"
```

---

### Task 3: Implement build_conversation_context()

**Files:**
- Modify: `backend/app/services/agent_service.py`

- [ ] **Step 1: Add the import at top of agent_service.py**

Add after line 7 (`from pathlib import Path`):

```python
from pathlib import Path  # already exists
```

No new import needed — `Path` is already imported at line 7. The function also needs `TaskLock`, so add this import near the top:

```python
from app.services.task_lock import TaskLock
```

Note: `TaskLock` is currently only imported in `workforce.py` and `chat.py`, not in `agent_service.py`. Add it after the existing app imports (after line 22).

- [ ] **Step 2: Add build_conversation_context() function**

Add after the `_extract_summary()` function (after line 166) in `backend/app/services/agent_service.py`:

```python
def build_conversation_context(task_lock: TaskLock) -> str:
    """Build structured context from previous workforce rounds.

    Returns a formatted string summarizing all previous rounds'
    task content, results, and generated files. Returns empty string
    if no conversation history exists.
    """
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
                files.extend(
                    str(f) for f in dir_path.rglob("*") if f.is_file()
                )
        if files:
            parts.append(f"\nGenerated Files: {files}")

    return "\n".join(parts)
```

- [ ] **Step 3: Run tests to verify they pass**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
source workspace/.venv/bin/activate
PYTHONPATH=. python -m pytest tests/test_conversation_context.py -v
```

Expected: All 6 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/agent_service.py
git commit -m "feat: add build_conversation_context() for multi-round history"
```

---

### Task 4: Update Task Decomposer Prompt

**Files:**
- Modify: `backend/app/services/agent_service.py:90-127`

- [ ] **Step 1: Replace the decomposition_principles section**

In `backend/app/services/agent_service.py`, replace the entire `TASK_DECOMPOSER_PROMPT_TEMPLATE` (lines 90-127) with:

```python
TASK_DECOMPOSER_PROMPT_TEMPLATE = """\
You decompose complex tasks into smaller, actionable subtasks for a \
multi-agent workforce.

<operating_environment>
- **System**: {platform_system} ({platform_machine})
- **Working Directory**: `{working_directory}`. All file output MUST be \
saved to this directory. Use absolute paths based on this directory in \
subtask descriptions. Do NOT use generic paths like /workspace, /output, \
or /tmp — always use the working directory above.
- **Current Date**: {now_str}
</operating_environment>

<available_workers>
The workforce has these specialized agents:
- **Browser Agent**: Web research and information gathering from the internet.
- **Developer Agent**: Code writing, execution, and technical implementation.
- **Document Agent**: Document creation (Word, PDF, HTML, PowerPoint, Excel).
</available_workers>

<decomposition_principles>
- **Self-contained subtasks**: Each subtask MUST be fully independent and \
understandable in isolation. Do NOT use relative references like "based on \
the previous step", "from the first task", or "using the above results". \
If a subtask needs upstream output, explicitly describe the required \
content (e.g., "Analyze the document titled 'React Framework Comparison' \
saved at {working_directory}/comparison.md").
- **Strategic grouping**: Sequential actions that require the same worker \
type SHOULD be grouped into a single subtask to reduce scheduling \
overhead. For example, "search for React info" + "search for Vue info" \
should be one Browser Agent subtask, not two.
- **Aggressive parallelization**: Different worker specializations MUST be \
split into separate subtasks to enable parallel execution. Multiple \
independent items of the same type SHOULD also be split into parallel \
subtasks when they don't share state.
- **Balanced granularity**: Each subtask should be large enough to be \
meaningful and small enough for effective parallelism. Avoid \
over-decomposition — splitting into too many tiny tasks adds overhead \
without benefit.
- Match subtasks to agent capabilities: research tasks for Browser Agent, \
coding tasks for Developer Agent, document tasks for Document Agent.
- Identify dependencies between subtasks and order them logically. \
Independent subtasks should be marked for parallel execution.
- NEVER ask agents to extract raw HTML or full page source code.
- NEVER create overly detailed extraction schemas.
- Focus on high-level goals: browse, summarize, write, code.
- Each subtask description should be self-contained with enough context \
for the assigned agent to work independently.
- When a subtask requires file output, specify the exact file path using \
the working directory (e.g., `{working_directory}/output.py`).
</decomposition_principles>
"""
```

- [ ] **Step 2: Verify the prompt renders without errors**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
source workspace/.venv/bin/activate
PYTHONPATH=. python -c "
from app.services.agent_service import TASK_DECOMPOSER_PROMPT_TEMPLATE
result = TASK_DECOMPOSER_PROMPT_TEMPLATE.format(
    platform_system='Darwin', platform_machine='arm64',
    working_directory='/tmp/test', now_str='2026-03-29 12:00',
)
assert 'Self-contained subtasks' in result
assert 'Strategic grouping' in result
assert 'Aggressive parallelization' in result
assert 'Balanced granularity' in result
assert '2-5' not in result
print('Prompt OK, length:', len(result))
"
```

Expected: `Prompt OK, length: <number>` with no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/agent_service.py
git commit -m "feat: enhance decomposer prompt with independence, grouping, and parallelization rules"
```

---

### Task 5: Inject Context in CapeWorkforce.run()

**Files:**
- Modify: `backend/app/agents/workforce.py:245-258`

- [ ] **Step 1: Add import for build_conversation_context**

In `backend/app/agents/workforce.py`, add after line 22 (`from app.services.task_lock import TaskLock`):

```python
from app.services.agent_service import build_conversation_context
```

- [ ] **Step 2: Modify the run() method to inject and restore context**

Replace the `run()` method (lines 245-258) with:

```python
    async def run(self, question: str):
        task_content = question + DEFAULT_SUMMARY_PROMPT
        main_task = Task(content=task_content, id=f"main_{uuid4().hex[:8]}")
        self.task_lock.status = Status.decomposing

        # Inject conversation history so the decomposer knows what
        # previous rounds accomplished (files created, results, etc.)
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

            # Restore original content to avoid polluting the task tree
            if context:
                main_task.content = original_content

            return result
        except Exception as e:
            await self.task_lock.put_event("error", {
                "message": f"Workforce error: {str(e)}"
            })
            raise
```

- [ ] **Step 3: Verify import resolves**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
source workspace/.venv/bin/activate
PYTHONPATH=. python -c "from app.agents.workforce import CapeWorkforce; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/agents/workforce.py
git commit -m "feat: inject conversation history context into workforce decomposer"
```

---

### Task 6: Persist TaskLock Across Rounds and Append History

**Files:**
- Modify: `backend/app/api/chat.py`

- [ ] **Step 1: Add module-level TaskLock registry**

In `backend/app/api/chat.py`, add after `router = APIRouter(prefix="/api")` (after line 26):

```python
# Registry of active TaskLocks per conversation, preserving
# conversation_history across multiple workforce rounds.
_active_task_locks: dict[str, TaskLock] = {}
```

- [ ] **Step 2: Replace TaskLock creation with registry lookup**

Replace line 48-51:

```python
        task_lock = TaskLock(
            id=req.conversation_id,
            status=Status.classifying,
        )
```

With:

```python
        task_lock = _active_task_locks.get(req.conversation_id)
        if task_lock is None:
            task_lock = TaskLock(
                id=req.conversation_id,
                status=Status.classifying,
            )
            _active_task_locks[req.conversation_id] = task_lock
        else:
            # Reuse existing TaskLock (preserves conversation_history)
            # but reset per-round state
            task_lock.status = Status.classifying
            task_lock.queue = asyncio.Queue()
            task_lock.background_tasks = set()
```

- [ ] **Step 3: Append round result to conversation_history after workforce completion**

In the workforce "end" event handler, after the `content = await summarize_workforce_result(...)` block (after line 130), add history append. The section currently reads:

```python
                    if event["step"] == "end":
                        subtask_results = event["data"].get(
                            "subtask_results", {}
                        )
                        try:
                            content = await summarize_workforce_result(
                                subtask_results,
                                req.message,
                                provider,
                                model_name,
                                req.api_key,
                                req.api_base,
                            )
                        except Exception as e:
                            logger.warning(
                                f"Failed to summarize workforce result: {e}"
                            )
                            content = event["data"].get("content", "")

                        await add_message(
```

Add the history append right before the `await add_message(` line:

```python
                        # Persist round result for multi-turn context
                        task_lock.conversation_history.append({
                            "task_content": req.message,
                            "task_result": content,
                            "working_directory": task_lock.working_directory,
                        })

                        await add_message(
```

- [ ] **Step 4: Verify the full chat.py parses**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
source workspace/.venv/bin/activate
PYTHONPATH=. python -c "from app.api.chat import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Run all tests**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
source workspace/.venv/bin/activate
PYTHONPATH=. python -m pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/chat.py
git commit -m "feat: persist TaskLock across rounds and append workforce results to history"
```

---

### Task 7: Final Integration Verification

- [ ] **Step 1: Verify all imports resolve end-to-end**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
source workspace/.venv/bin/activate
PYTHONPATH=. python -c "
from app.services.task_lock import TaskLock
from app.services.agent_service import build_conversation_context, TASK_DECOMPOSER_PROMPT_TEMPLATE
from app.agents.workforce import CapeWorkforce
from app.api.chat import router, _active_task_locks

# Verify TaskLock has conversation_history
tl = TaskLock(id='test', status='classifying')
assert hasattr(tl, 'conversation_history')
assert tl.conversation_history == []

# Verify build_conversation_context works
tl.conversation_history.append({
    'task_content': 'test', 'task_result': 'done', 'working_directory': ''
})
ctx = build_conversation_context(tl)
assert '=== CONVERSATION HISTORY ===' in ctx

# Verify prompt has new rules
prompt = TASK_DECOMPOSER_PROMPT_TEMPLATE
assert 'Self-contained subtasks' in prompt
assert 'Strategic grouping' in prompt
assert 'Aggressive parallelization' in prompt

# Verify registry exists
assert isinstance(_active_task_locks, dict)

print('All integration checks passed')
"
```

Expected: `All integration checks passed`

- [ ] **Step 2: Run full test suite**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
source workspace/.venv/bin/activate
PYTHONPATH=. python -m pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 3: Final commit if any fixes were needed**

Only if previous steps required fixes:

```bash
git add -A
git commit -m "fix: integration fixes for decomposition and context injection"
```
