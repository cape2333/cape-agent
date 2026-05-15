"""Skill Miner: turn a successful trajectory into a reusable skill.

Triggers (any of):

  1. The Judge's `task_signature` has been seen ≥ MIN_RECURRENCE times
     in the last RECURRENCE_WINDOW_DAYS days, and no loaded skill
     already covers it.
  2. The trace has ≥ MIN_NONTRIVIAL_CALLS non-trivial tool calls
     (anything beyond skill_view / mark_insight), and no loaded skill
     already covers it.
  3. The agent recorded ≥ 1 `mark_insight` annotation in this round
     — see BS-5: annotations are the agent's subjective "this was
     mechanistically interesting" signal.

Pipeline:

    abstract → dedup-check → persist as probationary

There is no offline unit-test gate; the LLM judging an LLM's
walkthrough turned out to be a high-false-pass safety theatre.
Instead, runtime probation is the safety net: probationary skills
(`is_probationary=true`) auto-archive on the first failure attributed
to them, so a bad miner output cannot pollute the library long-term.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from camel.agents import ChatAgent

from app.models.skill_schemas import JudgeResult, SkillDetail, StepTraceEntry
from app.services.signature_log import SignatureLog, signature_log
from app.services.skill_logger import SkillLogger, skill_logger
from app.services.skill_service import SkillService, skill_service
from app.services.step_trace import StepTracer, step_tracer

logger = logging.getLogger(__name__)


MIN_RECURRENCE = 2  # signature must appear at least this many times across distinct conversations
RECURRENCE_WINDOW_DAYS = 30
MIN_NONTRIVIAL_CALLS = 3

# Tools that don't count as "real work" for the recurrence trigger.
TRIVIAL_TOOLS = {"skill_view", "mark_insight", "skill_manage"}


MINER_SYSTEM = """\
You abstract a single successful task trajectory into a reusable
skill. You are aggressive about PARAMETERISATION: any value that came
from the user's request or from runtime page state must be a parameter,
never hard-coded. Stable constants (target site domain, button names)
can be hard-coded.

If a step or detail is too specific to this one user's request and
would not generalise, omit it. Better a smaller skill than an
over-specified one.
"""


MINER_USER_TEMPLATE = """\
## Source Task
User request: {user_query}
Final outcome: {final_response}

## Judge Verdict
task_signature: {task_signature}
domain: {domain}
rationale: {rationale}

## Step Trace (chronological)
{trace_text}

## Agent Annotations (mark_insight)
These capture the agent's subjective observations of mechanisms a raw
trace would not reveal. Fold them into ## Pitfalls in the output.
{annotations_text}

## Existing skill descriptions (do NOT propose a near-duplicate)
{existing_descs}

## Bad / Good Parameterisation Examples
Bad: "Open https://flights.ctrip.com/?from=BJS&to=SHA&date=2026-06-01"
Good: "Open https://flights.ctrip.com/, then enter <origin> in the
       'From' field, <destination> in 'To', and pick <departure_date>"

## Risk-Level Heuristic
- "high"   — submits orders, makes payments, deletes data, sends
             external messages.  MUST set dry_run_stop_at.
- "medium" — creates persistent local state (files, accounts) but
             reversible.
- "low"    — read-only browsing, summarisation, search.

## Output
Respond with EXACTLY one SKILL.md document, starting with the YAML
frontmatter and nothing before it. Use this skeleton verbatim, filling
in the placeholders:

---
name: <kebab-case-name>
description: <one-line trigger description>
agent_type: browser | developer | document
version: 0
enabled: true
created_by: agent
created_at: ''
updated_at: ''
tags: [evolved, miner]
risk_level: low | medium | high
dry_run_stop_at: <required when risk_level=high; otherwise omit>
is_probationary: true
---

## Trigger Conditions
When this skill applies.

## Parameters
- `<param_name>`: <description, e.g. origin city code>
- ...

## Steps
1. ...
2. ...

## Pitfalls
- ... (incorporate annotations)

## Verification
- How to confirm success.
"""


DEDUP_SYSTEM = """\
You decide whether a candidate skill duplicates an existing one. Be
conservative: mark as duplicate only when the existing skill clearly
covers the same task class. Two skills covering the same general area
but with different concrete approaches are NOT duplicates.

Respond with EXACTLY one word: "duplicate" or "unique".
"""


def _format_trace(trace: list[StepTraceEntry], max_entries: int = 120) -> str:
    if not trace:
        return "(no trace)"
    items = trace[-max_entries:]
    lines: list[str] = []
    for i, e in enumerate(items, 1):
        if e.kind == "skill_loaded":
            lines.append(f"{i}. [skill_loaded] {e.skill_in_focus}")
        elif e.kind == "tool_call":
            args = (e.tool_args_summary or "")[:200]
            lines.append(f"{i}. [call] {e.tool_name} args={args}")
        elif e.kind == "tool_result":
            res = (e.tool_result_summary or "")[:200]
            tag = "ERR" if e.was_error else "ok"
            lines.append(f"{i}. [result:{tag}] {e.tool_name} → {res}")
        elif e.kind == "annotation":
            ctx = f" | {e.annotation_context}" if e.annotation_context else ""
            lines.append(f"{i}. [annotation] {e.annotation_summary}{ctx}")
    return "\n".join(lines)


def _format_annotations(trace: list[StepTraceEntry]) -> str:
    notes = [e for e in trace if e.kind == "annotation"]
    if not notes:
        return "(none)"
    return "\n".join(
        f"- {n.annotation_summary}"
        + (f" | {n.annotation_context}" if n.annotation_context else "")
        for n in notes
    )


def _count_nontrivial_calls(trace: list[StepTraceEntry]) -> int:
    return sum(
        1
        for e in trace
        if e.kind == "tool_call" and e.tool_name not in TRIVIAL_TOOLS
    )


def _has_annotation(trace: list[StepTraceEntry]) -> bool:
    return any(e.kind == "annotation" for e in trace)


def should_mine(
    *,
    verdict: JudgeResult,
    trace: list[StepTraceEntry],
    conversation_id: str,
    siglog: SignatureLog,
) -> tuple[bool, str]:
    """Decide whether to mine this trajectory.

    Returns (should_mine, reason). `reason` is logged so we can audit
    why a trajectory was or wasn't promoted.
    """
    if not verdict.success or verdict.confidence < 0.6:
        return False, f"verdict not confident-success (confidence={verdict.confidence:.2f})"

    # If the agent already had a skill loaded that the judge attributed
    # successfully, the trajectory is "covered" — don't mine a duplicate.
    if verdict.used_skills:
        return False, f"task covered by existing skills: {verdict.used_skills}"

    if verdict.task_signature:
        occurrences = siglog.count_recent(
            verdict.task_signature,
            days=RECURRENCE_WINDOW_DAYS,
            exclude_conversation_id=conversation_id,
        )
        if occurrences >= MIN_RECURRENCE:
            return True, f"recurring signature ({occurrences} prior occurrences)"

    n_calls = _count_nontrivial_calls(trace)
    if n_calls >= MIN_NONTRIVIAL_CALLS:
        return True, f"non-trivial trajectory ({n_calls} tool calls)"

    if _has_annotation(trace):
        return True, "agent annotated this trajectory"

    return False, "no trigger met"


def _extract_skill_md(text: str) -> Optional[str]:
    """Pull a `---\\n...\\n---` SKILL.md document out of LLM output."""
    m = re.search(r"(---\s*\n.*?---\s*\n.*)", text, re.DOTALL)
    if not m:
        return None
    return m.group(1).strip()


class SkillMiner:
    def __init__(
        self,
        model,
        svc: Optional[SkillService] = None,
        log: Optional[SkillLogger] = None,
        siglog: Optional[SignatureLog] = None,
    ):
        self._model = model
        self._svc = svc or skill_service
        self._log = log or skill_logger
        self._siglog = siglog or signature_log

    async def maybe_mine(
        self,
        *,
        conversation_id: str,
        round_idx: int,
        user_query: str,
        final_response: str,
        verdict: JudgeResult,
        trace: Optional[list[StepTraceEntry]] = None,
        tracer: Optional[StepTracer] = None,
    ) -> Optional[SkillDetail]:
        """Mine the trajectory if triggers fire. Returns the created
        skill on success, None otherwise. Never raises — exceptions are
        logged and treated as "no skill created"."""
        tracer = tracer or step_tracer
        if trace is None:
            trace = tracer.read_round(conversation_id, round_idx)

        ok, reason = should_mine(
            verdict=verdict,
            trace=trace,
            conversation_id=conversation_id,
            siglog=self._siglog,
        )
        logger.info(
            "Miner trigger check: %s (%s)",
            "MINE" if ok else "skip",
            reason,
        )
        if not ok:
            return None

        try:
            skill_md = await self._abstract(
                user_query=user_query,
                final_response=final_response,
                verdict=verdict,
                trace=trace,
            )
        except Exception as exc:
            logger.warning("Miner abstraction failed: %s", exc, exc_info=exc)
            return None
        if not skill_md:
            logger.warning("Miner produced no skill markdown")
            return None

        fm, body = self._svc.parse_skill_md_from_text(skill_md)
        name = fm.get("name") or ""
        description = fm.get("description") or ""
        agent_type = fm.get("agent_type") or "browser"
        if not name or not description:
            logger.warning("Miner output missing name/description")
            return None

        # Dedup: ask the LLM whether the candidate near-duplicates any
        # existing skill in the same agent_type bucket.
        existing = [
            s for s in self._svc.list_skills(agent_type=agent_type, enabled=True)
        ]
        is_dup = await self._is_duplicate(description, existing)
        if is_dup:
            logger.info("Miner: candidate is duplicate of existing skill; skipping")
            return None

        # Make sure the name doesn't collide; if it does, suffix.
        original_name = name
        if self._svc.find_skill_dir(name):
            for i in range(2, 20):
                cand = f"{original_name}-{i}"
                if not self._svc.find_skill_dir(cand):
                    name = cand
                    break
            else:
                logger.warning("Miner: cannot find a free skill name; aborting")
                return None

        # Bundle the candidate's metadata for persistence. Probation is
        # the safety net — there is no offline gate to clear first.
        candidate = SkillDetail(
            name=name,
            description=description,
            agent_type=agent_type,
            version=0,
            enabled=True,
            created_by="agent",
            created_at="",
            updated_at="",
            tags=fm.get("tags") or ["evolved", "miner"],
            risk_level=fm.get("risk_level") or "low",
            dry_run_stop_at=fm.get("dry_run_stop_at"),
            is_probationary=True,
            content=body.strip(),
            raw="",
            files=[],
        )

        # Persist. We hand-build the SKILL.md so we can include the
        # extended frontmatter fields (risk_level, is_probationary).
        full_fm = {
            "name": name,
            "description": description,
            "agent_type": agent_type,
            "version": 0,
            "enabled": True,
            "created_by": "agent",
            "created_at": "",
            "updated_at": "",
            "tags": candidate.tags,
            "risk_level": candidate.risk_level,
            "dry_run_stop_at": candidate.dry_run_stop_at,
            "is_probationary": True,
        }
        full_md = self._svc._build_skill_md(full_fm, candidate.content)
        # Use SkillService's create_skill path to get directory + snapshot
        # invalidation. It will overwrite frontmatter — that's fine, we
        # pass the same canonical fields plus tags.
        created = self._svc.create_skill(
            name=name,
            description=description,
            agent_type=agent_type,
            content=candidate.content,
            tags=candidate.tags,
            created_by="agent",
        )

        # Now overwrite the SKILL.md with the full frontmatter so
        # risk_level / dry_run_stop_at / is_probationary persist.
        skill_dir = self._svc.find_skill_dir(name)
        if skill_dir:
            (skill_dir / "SKILL.md").write_text(full_md, encoding="utf-8")
            self._svc._invalidate_snapshot()

        self._log.log_event(
            "skill_created", name, agent_type, conversation_id,
            extra={"source": "miner", "trigger": reason},
        )
        logger.info("Miner: created skill '%s' (agent=%s, risk=%s)", name, agent_type, candidate.risk_level)
        return self._svc.get_skill(name)

    async def _abstract(
        self,
        *,
        user_query: str,
        final_response: str,
        verdict: JudgeResult,
        trace: list[StepTraceEntry],
    ) -> str:
        existing = self._svc.list_skills(enabled=True)
        existing_descs = "\n".join(f"- {s.name}: {s.description}" for s in existing) or "(none)"
        user = MINER_USER_TEMPLATE.format(
            user_query=user_query[:2000],
            final_response=final_response[:4000],
            task_signature=verdict.task_signature,
            domain=verdict.domain,
            rationale=verdict.rationale[:1000],
            trace_text=_format_trace(trace),
            annotations_text=_format_annotations(trace),
            existing_descs=existing_descs[:4000],
        )
        agent = ChatAgent(system_message=MINER_SYSTEM, model=self._model)
        response = await agent.astep(user)
        text = ""
        if response and response.msgs:
            text = response.msgs[0].content or ""
        return _extract_skill_md(text) or ""

    async def _is_duplicate(
        self, candidate_desc: str, existing: list
    ) -> bool:
        if not existing:
            return False
        existing_block = "\n".join(
            f"- {s.name}: {s.description}" for s in existing
        )
        prompt = (
            f"## Candidate\n{candidate_desc}\n\n"
            f"## Existing\n{existing_block}\n\n"
            "Is the candidate a near-duplicate of any existing entry? "
            "Reply with one word."
        )
        agent = ChatAgent(system_message=DEDUP_SYSTEM, model=self._model)
        try:
            response = await agent.astep(prompt)
        except Exception:
            return False
        text = ""
        if response and response.msgs:
            text = (response.msgs[0].content or "").strip().lower()
        return text.startswith("dup")
