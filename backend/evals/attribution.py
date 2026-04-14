"""Failure attribution — map eval failures to specific pipeline stages.

When a case fails, we want to know *which* component is responsible so
prompt/code changes can target the right place.  The Cape Agent pipeline
has these stages (in order):

    1. CLASSIFICATION      — classify_question routes simple vs workforce
    2. DECOMPOSITION       — task decomposer splits the main task
    3. TASK_ASSIGNMENT     — coordinator assigns subtasks to workers
    4. AGENT_EXECUTION     — the assigned worker runs to completion
    5. TOOL_FAILURE        — a toolkit call raised an error
    6. TIMEOUT             — workforce exceeded time budget
    7. SUMMARIZATION       — final summary missed critical content
    8. UNKNOWN             — none of the above matched

Attribution is a *best-effort heuristic* based on (a) which checks failed
and (b) the SSE event stream captured during execution.  It is not
perfect, but it's dramatically more actionable than a single pass-rate
number: knowing "70% of failures are in decomposition" tells you where
to focus.
"""

from enum import Enum
from typing import Optional


class FailureStage(str, Enum):
    CLASSIFICATION = "classification"
    DECOMPOSITION = "decomposition"
    TASK_ASSIGNMENT = "task_assignment"
    AGENT_EXECUTION = "agent_execution"
    TOOL_FAILURE = "tool_failure"
    TIMEOUT = "timeout"
    SUMMARIZATION = "summarization"
    UNKNOWN = "unknown"


# Check-key prefixes that signal specific failure stages
_CLASSIFICATION_KEYS = ("classification",)
_FILE_KEYS = ("file_exists:", "not_empty:", "min_size:")
_QUALITY_KEYS = ("quality",)
_SYNTAX_KEYS = ("syntax:",)
_RUN_KEYS = ("runs:",)


def _has_failed_prefix(checks: dict[str, bool], prefixes: tuple) -> bool:
    return any(
        not passed and any(k.startswith(p) or k == p for p in prefixes)
        for k, passed in checks.items()
    )


def _events_by_step(events: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for ev in events:
        grouped.setdefault(ev.get("step", ""), []).append(ev)
    return grouped


def attribute_failure(
    passed_checks: dict[str, bool],
    events: list[dict],
    error: Optional[str] = None,
) -> Optional[FailureStage]:
    """Return the most likely failure stage, or ``None`` if the case
    actually passed (i.e. every check is True and there is no error).
    """
    all_passed = passed_checks and all(passed_checks.values())
    if all_passed and not error:
        return None

    # --- Timeout / hard error first ---
    if error:
        err_lower = error.lower()
        if "timeout" in err_lower or "timed out" in err_lower:
            return FailureStage.TIMEOUT

    grouped = _events_by_step(events)

    # Workforce-level error event
    for ev in grouped.get("error", []):
        msg = (ev.get("data", {}).get("message") or "").lower()
        if "timeout" in msg:
            return FailureStage.TIMEOUT
        if "tool" in msg:
            return FailureStage.TOOL_FAILURE

    # --- Stage 1: classification check failed ---
    if _has_failed_prefix(passed_checks, _CLASSIFICATION_KEYS):
        return FailureStage.CLASSIFICATION

    # --- Stage 2: no decomposition happened (or empty sub_tasks) ---
    decomp_events = grouped.get("decompose_progress", [])
    if decomp_events:
        last = decomp_events[-1]
        sub_tasks = last.get("data", {}).get("sub_tasks", [])
        if not sub_tasks:
            return FailureStage.DECOMPOSITION

    # --- Stage 3: task assignment issues ---
    # agents listed in expected but never activated suggests assignment bug
    activated_names = [
        (ev.get("data", {}).get("agent_name") or "").lower()
        for ev in grouped.get("activate_agent", [])
    ]
    if (
        _has_failed_prefix(passed_checks, ("agent_used:",))
        and not activated_names
    ):
        return FailureStage.TASK_ASSIGNMENT

    # --- Stage 4: task failed state in the event stream ---
    for ev in grouped.get("task_state", []):
        data = ev.get("data", {})
        if data.get("state") == "failed":
            msg = (data.get("result") or "").lower()
            if "tool" in msg:
                return FailureStage.TOOL_FAILURE
            return FailureStage.AGENT_EXECUTION

    # --- Stage 5: files missing / syntax broken ---
    if _has_failed_prefix(passed_checks, _FILE_KEYS):
        return FailureStage.AGENT_EXECUTION
    if _has_failed_prefix(passed_checks, _SYNTAX_KEYS):
        return FailureStage.AGENT_EXECUTION
    if _has_failed_prefix(passed_checks, _RUN_KEYS):
        return FailureStage.AGENT_EXECUTION

    # --- Stage 6: everything ran but quality is low / keywords missing ---
    if _has_failed_prefix(passed_checks, _QUALITY_KEYS):
        return FailureStage.SUMMARIZATION
    if _has_failed_prefix(passed_checks, ("contains:", "answer_contains:")):
        return FailureStage.SUMMARIZATION

    return FailureStage.UNKNOWN


def summarize_failures(
    stage_counts: dict[FailureStage, int], total_failures: int,
) -> list[str]:
    """Return human-readable lines sorted by count (desc)."""
    if total_failures == 0:
        return ["No failures."]

    lines = []
    ordered = sorted(
        stage_counts.items(), key=lambda kv: kv[1], reverse=True,
    )
    for stage, count in ordered:
        if count == 0:
            continue
        pct = count / total_failures * 100
        lines.append(f"  {stage.value:<20} {count:>3}  ({pct:.0f}%)")
    return lines
