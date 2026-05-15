from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

RiskLevel = Literal["low", "medium", "high"]


class SkillMeta(BaseModel):
    name: str
    description: str
    agent_type: Literal["browser", "developer", "document"]
    version: int = 1
    enabled: bool = True
    created_by: Literal["agent", "user"] = "user"
    created_at: str = ""
    updated_at: str = ""
    tags: list[str] = Field(default_factory=list)
    # ── evolution fields ─────────────────────────────────────────
    risk_level: RiskLevel = "low"
    # For risk_level="high": describe the last safe step before the
    # destructive/irreversible action. Agents executing the skill are
    # expected to halt here and request user confirmation rather than
    # proceed unattended. Example for ctrip-flight-booking:
    # "click the 'Confirm Order' button"
    dry_run_stop_at: Optional[str] = None
    # New skills start probationary. A skill is "promoted" only after
    # 3 successful uses with no failures. On any failure during
    # probation, the skill is auto-archived.
    is_probationary: bool = False


class SkillDetail(SkillMeta):
    content: str = ""
    raw: str = ""
    files: list[str] = Field(default_factory=list)


class SkillCreate(BaseModel):
    name: str
    description: str
    agent_type: Literal["browser", "developer", "document"]
    content: str
    tags: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = "low"
    dry_run_stop_at: Optional[str] = None


class SkillUpdate(BaseModel):
    description: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    enabled: Optional[bool] = None
    risk_level: Optional[RiskLevel] = None
    dry_run_stop_at: Optional[str] = None


class SkillStats(BaseModel):
    name: str
    loads: int = 0
    patches: int = 0
    last_used: Optional[str] = None
    # ── utility tracking ─────────────────────────────────────────
    n_succ: int = 0
    n_fail: int = 0
    last_succ_at: Optional[str] = None
    last_fail_at: Optional[str] = None
    # Bounded FIFO lists of recent outcome timestamps. Used to compute
    # windowed utility (e.g. last-30-day success rate) without scanning
    # events.jsonl. Capped at 50 entries each on write.
    recent_succ: list[str] = Field(default_factory=list)
    recent_fail: list[str] = Field(default_factory=list)
    # Laplace-smoothed cumulative utility = (n_succ + 1) / (n_succ + n_fail + 2)
    # Computed lazily; not persisted (kept derivable from counters).
    utility: float = 0.5
    # Windowed utility over the lookback in `recent_succ`/`recent_fail`.
    # Computed lazily; not persisted.
    recent_utility_30d: float = 0.5


class SkillLogEntry(BaseModel):
    event: str
    skill: str
    agent_type: str
    conversation_id: Optional[str] = None
    ts: str


class InsightRecord(BaseModel):
    agent_type: Literal["browser", "developer", "document"]
    summary: str
    context: str = ""
    conversation_id: str = ""
    timestamp: str = ""


# ── Judge & evolution schemas ───────────────────────────────────


class JudgeResult(BaseModel):
    """Output of the Task Judge after each task round."""

    success: bool
    confidence: float = Field(ge=0.0, le=1.0)
    task_signature: str = ""
    domain: str = ""
    used_skills: list[str] = Field(default_factory=list)
    failed_skill: Optional[str] = None
    failure_reason: Optional[str] = None
    rationale: str = ""


class StepTraceEntry(BaseModel):
    """A single step in a task round trace."""

    ts: str
    kind: Literal["tool_call", "tool_result", "skill_loaded", "annotation"]
    tool_name: Optional[str] = None
    tool_args_summary: Optional[str] = None
    tool_result_summary: Optional[str] = None
    was_error: bool = False
    skill_in_focus: Optional[str] = None
    annotation_summary: Optional[str] = None
    annotation_context: Optional[str] = None
