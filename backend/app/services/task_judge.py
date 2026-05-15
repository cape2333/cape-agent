"""Task Judge: LLM-based scoring of every chat-task outcome.

This is the foundation of the self-evolving skill loop. Unlike the
previous mark_insight-only flow that fired on agent self-report, the
Judge runs **after every task** and produces:

  - success / failure verdict + confidence
  - canonical task signature (used by the Miner to detect recurrence)
  - failure attribution to a specific loaded skill (if any)

Outputs feed three downstream paths:
  1. `SkillLogger.record_outcome(...)` — utility counters for each
     skill that was used this round.
  2. `SkillMiner` — successful novel trajectories become skill drafts.
  3. `Frontend` — judge events become user-visible evolution signals.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from camel.agents import ChatAgent

from app.models.skill_schemas import JudgeResult, StepTraceEntry

logger = logging.getLogger(__name__)


JUDGE_SYSTEM_PROMPT = """\
You are a Task Judge for an autonomous agent system. Your job is to
evaluate whether the agent completed the user's task and, if not,
identify which loaded skill was most likely responsible for the failure.

Be strict and honest:
- "Partially answered" or "found information but did not act" counts as
  failure unless the user only asked for information.
- "Refused to help" without good cause is failure.
- "Completed task but with errors mid-way that the agent recovered from"
  is success.

You MUST respond with a single JSON object and nothing else.
"""


JUDGE_USER_PROMPT_TEMPLATE = """\
## User Request
{user_query}

## Agent's Final Response
{final_response}

## Skills That Were Loaded This Round
{skills_text}

## Step Trace (chronological)
{trace_text}

## Annotations the Agent Recorded
{annotations_text}

## Output Schema
Respond with EXACTLY this JSON shape (no markdown fence, no prose):
{{
  "success": true | false,
  "confidence": 0.0 to 1.0,
  "task_signature": "short canonical task description, e.g. 'book flight on ctrip' — domain + verb + key noun",
  "domain": "high-level domain bucket, e.g. 'browser-booking', 'doc-summarize', 'code-fix'",
  "used_skills": ["list of skill names that were actually consulted"],
  "failed_skill": "skill_name OR null — only set if failure can be attributed to one skill",
  "failure_reason": "short reason OR null",
  "rationale": "one short paragraph justifying your verdict"
}}
"""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[truncated {len(text) - limit} chars]"


def _format_trace(trace: list[StepTraceEntry], max_entries: int = 80) -> str:
    if not trace:
        return "(no trace recorded)"
    items = trace[-max_entries:]
    lines: list[str] = []
    for i, e in enumerate(items, 1):
        if e.kind == "skill_loaded":
            lines.append(f"{i}. [skill_loaded] {e.skill_in_focus}")
        elif e.kind == "tool_call":
            args = _truncate(e.tool_args_summary or "", 200)
            scope = f" (in skill={e.skill_in_focus})" if e.skill_in_focus else ""
            lines.append(f"{i}. [call] {e.tool_name}{scope} args={args}")
        elif e.kind == "tool_result":
            res = _truncate(e.tool_result_summary or "", 200)
            err = " ERROR" if e.was_error else ""
            scope = f" (in skill={e.skill_in_focus})" if e.skill_in_focus else ""
            lines.append(f"{i}. [result{err}] {e.tool_name}{scope} → {res}")
        elif e.kind == "annotation":
            ctx = f" | {e.annotation_context}" if e.annotation_context else ""
            lines.append(f"{i}. [annotation] {e.annotation_summary}{ctx}")
    return "\n".join(lines)


def _format_skills(skills: list[str]) -> str:
    if not skills:
        return "(none)"
    return "\n".join(f"- {s}" for s in skills)


def _format_annotations(trace: list[StepTraceEntry]) -> str:
    notes = [e for e in trace if e.kind == "annotation"]
    if not notes:
        return "(none)"
    lines = []
    for n in notes:
        ctx = f" | context: {n.annotation_context}" if n.annotation_context else ""
        lines.append(f"- {n.annotation_summary}{ctx}")
    return "\n".join(lines)


def _extract_json(text: str) -> Optional[dict]:
    """Extract the first JSON object from a string.

    Robust to LLMs wrapping JSON in ```json fences or trailing prose.
    """
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1)
    else:
        # Greedy match the outermost {...}
        first = text.find("{")
        last = text.rfind("}")
        if first == -1 or last == -1 or last < first:
            return None
        candidate = text[first : last + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


class TaskJudge:
    def __init__(self, model):
        self._model = model

    async def judge(
        self,
        user_query: str,
        final_response: str,
        loaded_skills: list[str],
        trace: list[StepTraceEntry],
    ) -> JudgeResult:
        """Score a single task round.

        Returns a JudgeResult with `confidence=0.0` if the judge LLM
        failed to produce parsable output. Callers should treat
        low-confidence verdicts conservatively (e.g., skip updating
        utility, or downgrade the signal).
        """
        prompt = JUDGE_USER_PROMPT_TEMPLATE.format(
            user_query=_truncate(user_query, 2000),
            final_response=_truncate(final_response, 4000),
            skills_text=_format_skills(loaded_skills),
            trace_text=_format_trace(trace),
            annotations_text=_format_annotations(trace),
        )

        agent = ChatAgent(
            system_message=JUDGE_SYSTEM_PROMPT,
            model=self._model,
        )

        try:
            response = await agent.astep(prompt)
        except Exception as e:
            logger.warning("Judge LLM call failed: %s", e)
            return JudgeResult(
                success=False,
                confidence=0.0,
                rationale=f"Judge LLM error: {e}",
            )

        text = ""
        try:
            if response and response.msgs:
                text = response.msgs[0].content or ""
        except Exception:
            text = ""

        data = _extract_json(text)
        if not data:
            logger.warning("Judge produced unparseable output: %s", text[:500])
            return JudgeResult(
                success=False,
                confidence=0.0,
                rationale="Judge produced unparseable output",
                used_skills=loaded_skills,
            )

        # Cross-check `used_skills` against what was actually loaded;
        # the LLM sometimes invents names. Intersect.
        loaded_set = set(loaded_skills)
        claimed_used = data.get("used_skills") or []
        cleaned_used = [s for s in claimed_used if s in loaded_set] or loaded_skills

        failed_skill = data.get("failed_skill")
        if failed_skill and failed_skill not in loaded_set:
            failed_skill = None

        try:
            return JudgeResult(
                success=bool(data.get("success", False)),
                confidence=float(data.get("confidence", 0.5)),
                task_signature=str(data.get("task_signature") or "")[:200],
                domain=str(data.get("domain") or "")[:80],
                used_skills=cleaned_used,
                failed_skill=failed_skill,
                failure_reason=(data.get("failure_reason") or None),
                rationale=str(data.get("rationale") or "")[:2000],
            )
        except (ValueError, TypeError) as e:
            logger.warning("Judge JSON failed schema validation: %s", e)
            return JudgeResult(
                success=False,
                confidence=0.0,
                rationale=f"Judge schema validation failed: {e}",
                used_skills=loaded_skills,
            )
