# Fix Working Directory & Task Reliability

**Date**: 2026-03-26
**Status**: Approved

## Problem

When a user asks Cape Agent to "write a snake game and run it", the task fails because:

1. **Task Decomposer has no working directory context** — it invents `/workspace` paths
2. **macOS root filesystem is read-only** — `/workspace` cannot be created
3. **Quality evaluator marks the task as failed** — even though code was written and tested successfully
4. **TerminalToolkit timeout is 30s** — too short for install + code + run

## Solution

Four changes across three files.

### 1. Persistent Working Directory (`agent_service.py`)

Replace `tempfile.mkdtemp()` with `~/.cape-agent/workspace/{conversation_id}/`.

- Uses `task_lock.id` as the conversation identifier (already unique)
- Created with `os.makedirs(path, exist_ok=True)`
- Survives app restarts; users can find output files

### 2. Inject Environment Info into Coordinator & Task Decomposer Prompts (`agent_service.py`)

Convert `COORDINATOR_PROMPT` and `TASK_DECOMPOSER_PROMPT` from static strings to templates. Inject:

- `working_directory` — the actual persistent path
- `platform_system` / `platform_machine` — OS info
- `now_str` — current date

Add explicit instruction: "All file output MUST use this directory. Do NOT invent paths like /workspace or /output."

Format these templates in `build_workforce()` where the working directory is known.

### 3. TerminalToolkit Timeout (`developer.py`)

Change `timeout=30.0` to `timeout=300.0` (5 minutes). Allows complex tasks (dependency installation + code writing + execution) to complete.

### 4. Quality Evaluation Retry + Fallback (`workforce.py`)

Rewrite `_analyze_task` to:

- Call `super()._analyze_task()` with up to 3 retries on None/exception
- After 3 failures on a normal task: accept with score 80 (task did work, evaluation broke)
- After 3 failures on an already-failed task: raise RuntimeError to halt

Keep existing `QUALITY_ACCEPT_THRESHOLD = 85` logic unchanged.

## Files Changed

| File | Change |
|------|--------|
| `backend/app/services/agent_service.py` | Persistent working dir + prompt templates |
| `backend/app/agents/factory/developer.py` | timeout 30 → 300 |
| `backend/app/agents/workforce.py` | `_analyze_task` retry + fallback |

## Verification

After changes, the "write a snake game and run it" task should:

1. Task Decomposer generates paths under `~/.cape-agent/workspace/...`
2. Developer Agent writes code to that directory and executes it
3. No `/workspace` errors
4. Task completes successfully on first attempt
