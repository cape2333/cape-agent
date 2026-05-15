"""Periodic library hygiene: archive low-utility skills, cap totals,
dedup by description hash.

Designed to be invoked by an admin endpoint or a future scheduled job.
All actions are reversible — archived skills are soft-disabled
(`enabled=False` with the `auto-archived` tag) so a user can re-enable
from the UI if the system makes a wrong call.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, Field

from app.models.skill_schemas import SkillMeta
from app.services.skill_logger import SkillLogger, skill_logger
from app.services.skill_service import SkillService, skill_service

logger = logging.getLogger(__name__)


# ── thresholds (tunable) ───────────────────────────────────────────

# Per-agent_type soft cap. When exceeded, archive the lowest-utility
# skills until under cap. 200 is generous for a personal workflow.
MAX_SKILLS_PER_TYPE = 200

# Archive a skill when utility drops below this, AND it has enough
# samples to be statistically meaningful, AND it hasn't been useful
# in a while.
ARCHIVE_UTILITY_BELOW = 0.30
ARCHIVE_MIN_TOTAL_OUTCOMES = 5
ARCHIVE_IDLE_DAYS = 60


class HygieneAction(BaseModel):
    skill: str
    action: str  # "archived" | "duplicate-merge" | "cap-archived"
    reason: str = ""


class HygieneReport(BaseModel):
    scanned: int = 0
    archived: int = 0
    duplicates_found: int = 0
    cap_archived: int = 0
    actions: list[HygieneAction] = Field(default_factory=list)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _description_hash(description: str) -> str:
    return hashlib.sha256(
        " ".join(description.lower().split()).encode("utf-8")
    ).hexdigest()


def _soft_archive(
    svc: SkillService,
    log: SkillLogger,
    skill: SkillMeta,
    reason: str,
    action_label: str,
    report: HygieneReport,
) -> None:
    """Disable a skill and tag it auto-archived. Reversible from UI."""
    skill_dir = svc.find_skill_dir(skill.name)
    if skill_dir is None:
        return
    md_path = skill_dir / "SKILL.md"
    fm, body = svc._parse_skill_md(md_path)
    fm["enabled"] = False
    tags = list(fm.get("tags") or [])
    if "auto-archived" not in tags:
        tags.append("auto-archived")
    fm["tags"] = tags
    fm["version"] = (fm.get("version") or 0) + 1
    fm["updated_at"] = _now().isoformat()
    md_path.write_text(svc._build_skill_md(fm, body), encoding="utf-8")
    svc._invalidate_snapshot()
    log.log_event(
        "skill_archived", skill.name, skill.agent_type,
        extra={"reason": reason},
    )
    report.actions.append(
        HygieneAction(skill=skill.name, action=action_label, reason=reason)
    )


def run_hygiene(
    svc: Optional[SkillService] = None,
    log: Optional[SkillLogger] = None,
) -> HygieneReport:
    """Sweep the skill library and apply archive / dedup decisions.

    Returns a HygieneReport summarising what changed. Safe to call
    repeatedly — actions are idempotent.
    """
    svc = svc or skill_service
    log = log or skill_logger
    report = HygieneReport()

    all_skills = svc.list_skills(enabled=True)
    report.scanned = len(all_skills)
    now = _now()

    # ── 1. Archive low-utility idle skills ────────────────────────
    for s in all_skills:
        stats = log.get_skill_stats(s.name)
        n_succ = stats.get("n_succ", 0)
        n_fail = stats.get("n_fail", 0)
        total = n_succ + n_fail
        if total < ARCHIVE_MIN_TOTAL_OUTCOMES:
            continue
        utility = SkillLogger.compute_utility(stats)
        if utility >= ARCHIVE_UTILITY_BELOW:
            continue
        last_used = _parse_iso(stats.get("last_used"))
        if last_used and (now - last_used) < timedelta(days=ARCHIVE_IDLE_DAYS):
            # Still actively used despite low utility — leave it; the
            # user clearly wants it even though it fails sometimes.
            continue
        _soft_archive(
            svc, log, s,
            reason=(
                f"utility={utility:.2f} after {total} outcomes; "
                f"last_used={stats.get('last_used') or 'never'}"
            ),
            action_label="archived",
            report=report,
        )
        report.archived += 1

    # Refresh after archiving so caps + dedup operate on the survivors.
    survivors = svc.list_skills(enabled=True)

    # ── 2. Dedup by description hash ──────────────────────────────
    by_hash: dict[str, list[SkillMeta]] = {}
    for s in survivors:
        by_hash.setdefault(_description_hash(s.description), []).append(s)
    for group in by_hash.values():
        if len(group) < 2:
            continue
        # Keep the highest-utility one; archive the rest.
        ranked = sorted(
            group,
            key=lambda x: (
                SkillLogger.compute_utility(log.get_skill_stats(x.name)),
                # tie-break: keep the newer entry
                x.updated_at or "",
            ),
            reverse=True,
        )
        keeper = ranked[0]
        for dup in ranked[1:]:
            _soft_archive(
                svc, log, dup,
                reason=f"duplicate of {keeper.name} (same description hash)",
                action_label="duplicate-merge",
                report=report,
            )
            report.duplicates_found += 1

    # ── 3. Per-type cap ───────────────────────────────────────────
    survivors = svc.list_skills(enabled=True)
    by_type: dict[str, list[SkillMeta]] = {}
    for s in survivors:
        by_type.setdefault(s.agent_type, []).append(s)
    for agent_type, group in by_type.items():
        if len(group) <= MAX_SKILLS_PER_TYPE:
            continue
        excess = len(group) - MAX_SKILLS_PER_TYPE
        # Archive the lowest-utility tail.
        scored = sorted(
            group,
            key=lambda x: (
                SkillLogger.compute_utility(log.get_skill_stats(x.name)),
                _parse_iso(log.get_skill_stats(x.name).get("last_used"))
                or datetime(1970, 1, 1, tzinfo=timezone.utc),
            ),
        )
        for s in scored[:excess]:
            _soft_archive(
                svc, log, s,
                reason=f"cap exceeded for agent_type={agent_type} ({len(group)}>{MAX_SKILLS_PER_TYPE})",
                action_label="cap-archived",
                report=report,
            )
            report.cap_archived += 1

    logger.info(
        "Hygiene done: scanned=%d archived=%d duplicates=%d cap=%d",
        report.scanned,
        report.archived,
        report.duplicates_found,
        report.cap_archived,
    )
    return report


def check_duplicate_on_create(
    description: str,
    svc: Optional[SkillService] = None,
) -> Optional[str]:
    """Return the name of an existing skill with identical description, else None."""
    svc = svc or skill_service
    target_hash = _description_hash(description)
    for s in svc.list_skills():
        if _description_hash(s.description) == target_hash:
            return s.name
    return None
