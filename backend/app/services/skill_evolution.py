"""Post-task orchestration: Judge → utility → probation → Miner.

Runs after each completed chat-task round to close the Read-Write
Reflective Learning loop:

  1. Read the step trace for this round.
  2. Run the Task Judge → JudgeResult.
  3. Record the task signature for recurrence tracking.
  4. Update utility counters for every loaded skill (per-skill attribution).
  5. Handle probationary skills: auto-archive on failure, promote on 3 wins.
  6. If the round was successful and triggers fire, hand off to the
     Skill Miner.

This module is intentionally orchestration-only — heavy logic lives in
`task_judge.py`, `skill_miner.py`, and `skill_logger.py`. Keep this
thin so the post-task path is easy to reason about.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.models.skill_schemas import JudgeResult
from app.services.signature_log import SignatureLog, signature_log
from app.services.skill_logger import SkillLogger, skill_logger
from app.services.skill_miner import SkillMiner
from app.services.skill_service import SkillService, skill_service
from app.services.step_trace import StepTracer, step_tracer
from app.services.task_judge import TaskJudge

logger = logging.getLogger(__name__)


# Below this confidence we don't trust the verdict enough to update
# utility counters. Skills shouldn't be penalised by an unreliable
# judge.
MIN_JUDGE_CONFIDENCE_FOR_UTILITY = 0.5

# A probationary skill is promoted to non-probationary after this many
# consecutive successes with no intervening failures.
PROBATION_PROMOTION_THRESHOLD = 3


async def run_post_task_evolution(
    *,
    conversation_id: str,
    round_idx: int,
    user_query: str,
    final_response: str,
    judge_model,
    miner_model=None,
    svc: Optional[SkillService] = None,
    log: Optional[SkillLogger] = None,
    tracer: Optional[StepTracer] = None,
    siglog: Optional[SignatureLog] = None,
) -> JudgeResult:
    """Run Judge + utility updates + Miner after a task round.

    Returns the JudgeResult so callers can also log or surface it.
    Never raises — failures are logged and a low-confidence verdict
    is returned instead.
    """
    svc = svc or skill_service
    log = log or skill_logger
    tracer = tracer or step_tracer
    siglog = siglog or signature_log
    miner_model = miner_model or judge_model

    trace = tracer.read_round(conversation_id, round_idx)
    loaded_skills = tracer.skills_used_in_round(conversation_id, round_idx)

    judge = TaskJudge(model=judge_model)

    try:
        verdict = await judge.judge(
            user_query=user_query,
            final_response=final_response,
            loaded_skills=loaded_skills,
            trace=trace,
        )
    except Exception as exc:
        logger.warning("Judge raised during post-task evolution: %s", exc, exc_info=exc)
        return JudgeResult(
            success=False,
            confidence=0.0,
            rationale=f"Judge raised: {exc}",
            used_skills=loaded_skills,
        )

    # Record the signature regardless of confidence — recurrence
    # detection should not be silently disabled by a flaky judge.
    if verdict.task_signature:
        try:
            siglog.record(
                signature=verdict.task_signature,
                domain=verdict.domain,
                conversation_id=conversation_id,
            )
        except Exception as exc:
            logger.warning("Signature log write failed: %s", exc)

    if verdict.confidence >= MIN_JUDGE_CONFIDENCE_FOR_UTILITY:
        _apply_utility_updates(verdict, svc=svc, log=log, conversation_id=conversation_id)
        _handle_probation(verdict, svc=svc, log=log)
    else:
        logger.info(
            "Judge confidence=%.2f below threshold; skipping utility update "
            "for conversation %s round %d",
            verdict.confidence,
            conversation_id,
            round_idx,
        )

    # Skill mining: trigger when the round succeeded confidently.
    # Internal triggers (recurrence / non-trivial calls / annotations)
    # further filter — see SkillMiner.should_mine.
    try:
        miner = SkillMiner(model=miner_model, svc=svc, log=log, siglog=siglog)
        created = await miner.maybe_mine(
            conversation_id=conversation_id,
            round_idx=round_idx,
            user_query=user_query,
            final_response=final_response,
            verdict=verdict,
            trace=trace,
            tracer=tracer,
        )
        if created:
            logger.info("Miner created skill: %s", created.name)
    except Exception as exc:
        logger.warning("Miner raised: %s", exc, exc_info=exc)

    logger.info(
        "Post-task evolution: conv=%s round=%d success=%s confidence=%.2f "
        "used=%d failed_skill=%s",
        conversation_id,
        round_idx,
        verdict.success,
        verdict.confidence,
        len(verdict.used_skills),
        verdict.failed_skill,
    )
    return verdict


def _apply_utility_updates(
    verdict: JudgeResult,
    *,
    svc: SkillService,
    log: SkillLogger,
    conversation_id: str,
) -> None:
    """Per-skill outcome attribution.

    Every loaded skill inherits the round-level verdict, EXCEPT when
    the judge attributed the failure to one specific skill — in that
    case only that skill is marked failed, since the agent recovered
    around the others.
    """
    for skill_name in verdict.used_skills:
        detail = svc.get_skill(skill_name)
        if detail is None:
            continue
        if verdict.success:
            success_for_this = True
        else:
            success_for_this = (
                verdict.failed_skill is not None
                and skill_name != verdict.failed_skill
            )
        log.record_outcome(
            skill=skill_name,
            success=success_for_this,
            agent_type=detail.agent_type,
            conversation_id=conversation_id,
            failure_reason=(
                verdict.failure_reason
                if (not success_for_this and verdict.failure_reason)
                else None
            ),
        )


def _handle_probation(
    verdict: JudgeResult,
    *,
    svc: SkillService,
    log: SkillLogger,
) -> None:
    """Promote or auto-archive probationary skills based on the verdict.

    - Any failure of a probationary skill → soft-archive (enabled=False).
      Probationary skills must be reliable from day one; a single
      failure is enough to suspect the Miner abstracted poorly. The
      user can re-enable it via the UI if they disagree.
    - After PROBATION_PROMOTION_THRESHOLD consecutive successes →
      promote (clear `is_probationary`).
    """
    for skill_name in verdict.used_skills:
        detail = svc.get_skill(skill_name)
        if detail is None or not detail.is_probationary:
            continue

        skill_dir = svc.find_skill_dir(skill_name)
        if skill_dir is None:
            continue
        md_path = skill_dir / "SKILL.md"
        fm, body = svc._parse_skill_md(md_path)
        changed = False

        # Determine outcome of THIS skill in this round.
        if verdict.success:
            skill_succeeded = True
        else:
            skill_succeeded = (
                verdict.failed_skill is not None
                and skill_name != verdict.failed_skill
            )

        if not skill_succeeded:
            fm["enabled"] = False
            fm["is_probationary"] = False  # Final verdict — no more chances.
            tags = list(fm.get("tags") or [])
            if "auto-archived" not in tags:
                tags.append("auto-archived")
            fm["tags"] = tags
            changed = True
            log.log_event(
                "skill_archived", skill_name, detail.agent_type,
                extra={"reason": "probation-failed"},
            )
        else:
            stats = log.get_skill_stats(skill_name)
            if stats.get("n_succ", 0) >= PROBATION_PROMOTION_THRESHOLD:
                fm["is_probationary"] = False
                tags = list(fm.get("tags") or [])
                if "promoted" not in tags:
                    tags.append("promoted")
                fm["tags"] = tags
                changed = True
                log.log_event(
                    "skill_promoted", skill_name, detail.agent_type,
                    extra={"n_succ": stats.get("n_succ", 0)},
                )

        if changed:
            from datetime import datetime, timezone
            fm["version"] = (fm.get("version") or 0) + 1
            fm["updated_at"] = datetime.now(timezone.utc).isoformat()
            md_path.write_text(svc._build_skill_md(fm, body), encoding="utf-8")
            svc._invalidate_snapshot()
