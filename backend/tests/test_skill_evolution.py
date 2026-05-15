"""End-to-end tests for the self-evolution loop building blocks.

These do NOT spin up an LLM — they exercise the deterministic plumbing
around the Judge / Miner / Hygiene services. LLM-bound paths are mocked.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.models.skill_schemas import JudgeResult, StepTraceEntry
from app.services.signature_log import SignatureLog
from app.services.skill_evolution import run_post_task_evolution
from app.services.skill_hygiene import (
    HygieneReport,
    check_duplicate_on_create,
    run_hygiene,
)
from app.services.skill_logger import SkillLogger
from app.services.skill_miner import should_mine
from app.services.skill_service import SkillService
from app.services.step_trace import StepTracer


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def env(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    svc = SkillService(skills_dir=skills_dir)
    log = SkillLogger(log_dir=skills_dir / ".log")
    tracer = StepTracer(root=skills_dir / ".trace")
    siglog = SignatureLog(path=skills_dir / ".log" / "signatures.jsonl")
    return svc, log, tracer, siglog, skills_dir


def _make_skill(svc, name, description, agent_type="browser"):
    return svc.create_skill(
        name=name,
        description=description,
        agent_type=agent_type,
        content=f"## Steps\n1. Use {name}",
        created_by="agent",
    )


# ── utility tracking ────────────────────────────────────────────────


class TestUtility:
    def test_laplace_default_05(self, env):
        _, log, _, _, _ = env
        stats = log.get_skill_stats("never-used")
        assert SkillLogger.compute_utility(stats) == pytest.approx(0.5)

    def test_records_success_and_failure(self, env):
        _, log, _, _, _ = env
        log.record_outcome("s1", success=True, agent_type="browser")
        log.record_outcome("s1", success=True, agent_type="browser")
        log.record_outcome("s1", success=False, agent_type="browser")
        stats = log.get_skill_stats("s1")
        assert stats["n_succ"] == 2
        assert stats["n_fail"] == 1
        # Laplace: (2+1)/(3+2) = 0.6
        assert SkillLogger.compute_utility(stats) == pytest.approx(0.6)

    def test_recent_window_falls_back_when_empty(self, env):
        _, log, _, _, _ = env
        stats = log.get_skill_stats("s1")
        # Empty window → fall back to all-time utility.
        assert log.compute_recent_utility(stats, days=30) == pytest.approx(0.5)


# ── miner trigger logic ────────────────────────────────────────────


class TestMinerTrigger:
    def test_low_confidence_blocks_mining(self, env):
        _, _, _, siglog, _ = env
        verdict = JudgeResult(success=True, confidence=0.3)
        ok, _ = should_mine(verdict=verdict, trace=[], conversation_id="c1", siglog=siglog)
        assert not ok

    def test_failure_blocks_mining(self, env):
        _, _, _, siglog, _ = env
        verdict = JudgeResult(success=False, confidence=0.9)
        ok, _ = should_mine(verdict=verdict, trace=[], conversation_id="c1", siglog=siglog)
        assert not ok

    def test_used_skills_block_mining(self, env):
        _, _, _, siglog, _ = env
        verdict = JudgeResult(success=True, confidence=0.9, used_skills=["foo"])
        ok, _ = should_mine(verdict=verdict, trace=[], conversation_id="c1", siglog=siglog)
        assert not ok

    def test_nontrivial_trajectory_triggers(self, env):
        _, _, _, siglog, _ = env
        verdict = JudgeResult(success=True, confidence=0.9, used_skills=[])
        trace = [
            StepTraceEntry(ts="", kind="tool_call", tool_name=f"tool_{i}")
            for i in range(3)
        ]
        ok, reason = should_mine(verdict=verdict, trace=trace, conversation_id="c1", siglog=siglog)
        assert ok
        assert "non-trivial" in reason

    def test_annotation_triggers(self, env):
        _, _, _, siglog, _ = env
        verdict = JudgeResult(success=True, confidence=0.9, used_skills=[])
        trace = [StepTraceEntry(ts="", kind="annotation", annotation_summary="!")]
        ok, _ = should_mine(verdict=verdict, trace=trace, conversation_id="c1", siglog=siglog)
        assert ok

    def test_recurrence_triggers(self, env):
        _, _, _, siglog, _ = env
        # Record two prior occurrences in OTHER conversations.
        siglog.record("book flight ctrip", "browser-booking", "old-conv-1")
        siglog.record("book flight ctrip", "browser-booking", "old-conv-2")
        verdict = JudgeResult(
            success=True, confidence=0.9, used_skills=[],
            task_signature="book flight ctrip",
        )
        ok, reason = should_mine(verdict=verdict, trace=[], conversation_id="now-conv", siglog=siglog)
        assert ok
        assert "recurring" in reason


# ── hygiene ────────────────────────────────────────────────────────


class TestHygiene:
    def test_archives_low_utility_idle(self, env, monkeypatch):
        svc, log, _, _, _ = env
        _make_skill(svc, "bad", "thing that fails a lot")
        # 1 success, 9 failures → utility ≈ 0.17
        log.record_outcome("bad", success=True, agent_type="browser")
        for _ in range(9):
            log.record_outcome("bad", success=False, agent_type="browser")
        # Patch the idle threshold to make the test fast.
        from app.services import skill_hygiene
        monkeypatch.setattr(skill_hygiene, "ARCHIVE_IDLE_DAYS", 0)
        # Force last_used into the past so "still active" check passes.
        stats = log.get_skill_stats("bad")
        import json
        log._stats_path.write_text(
            json.dumps({"bad": {**stats, "last_used": "1970-01-01T00:00:00+00:00"}}),
            encoding="utf-8",
        )
        report = run_hygiene(svc=svc, log=log)
        assert report.archived == 1
        # Skill is now disabled.
        detail = svc.get_skill("bad")
        assert detail.enabled is False
        assert "auto-archived" in detail.tags

    def test_dedup_archives_duplicates(self, env):
        svc, log, _, _, _ = env
        _make_skill(svc, "a", "Book a flight on Ctrip")
        _make_skill(svc, "b", "Book a flight on Ctrip")
        report = run_hygiene(svc=svc, log=log)
        assert report.duplicates_found == 1

    def test_check_duplicate(self, env):
        svc, _, _, _, _ = env
        _make_skill(svc, "x", "Summarise a PDF document into bullet points")
        dup = check_duplicate_on_create(
            "Summarise a PDF document into bullet points", svc=svc
        )
        assert dup == "x"
        nope = check_duplicate_on_create("Something else entirely", svc=svc)
        assert nope is None


# ── evolution orchestration ────────────────────────────────────────


class FakeJudgeAgent:
    """Stand-in for the LLM judge — returns canned JSON."""

    def __init__(self, verdict_dict):
        self._payload = verdict_dict

    async def astep(self, _prompt):
        import json as _json

        class _R:
            def __init__(self, content):
                self.msgs = [type("M", (), {"content": content})]

        return _R(_json.dumps(self._payload))


class TestEvolutionLoop:
    @pytest.mark.asyncio
    async def test_judge_success_records_utility(self, env, monkeypatch):
        svc, log, tracer, siglog, _ = env
        _make_skill(svc, "the-skill", "Do the thing")
        # Simulate the trace showing the agent loaded the skill.
        tracer.record_skill_loaded("conv-x", 0, "the-skill")

        # Patch TaskJudge to return a canned success verdict without
        # needing an LLM. Also patch the Miner so no SKILL.md is
        # written to disk during this test.
        from app.services import task_judge as tj_mod
        from app.services import skill_evolution as evo_mod
        from app.services import skill_miner as miner_mod

        async def fake_judge(self, *, user_query, final_response, loaded_skills, trace):
            return JudgeResult(
                success=True,
                confidence=0.9,
                task_signature="do the thing",
                domain="generic",
                used_skills=loaded_skills,
                failed_skill=None,
                failure_reason=None,
                rationale="ok",
            )

        async def fake_maybe_mine(self, **kwargs):
            return None

        monkeypatch.setattr(tj_mod.TaskJudge, "judge", fake_judge)
        monkeypatch.setattr(miner_mod.SkillMiner, "maybe_mine", fake_maybe_mine)

        verdict = await run_post_task_evolution(
            conversation_id="conv-x",
            round_idx=0,
            user_query="do the thing",
            final_response="done",
            judge_model=None,  # unused thanks to fake_judge
            svc=svc, log=log, tracer=tracer, siglog=siglog,
        )
        assert verdict.success
        stats = log.get_skill_stats("the-skill")
        assert stats["n_succ"] == 1
        assert stats["n_fail"] == 0

    @pytest.mark.asyncio
    async def test_judge_failure_with_attribution_only_marks_one(
        self, env, monkeypatch
    ):
        svc, log, tracer, siglog, _ = env
        _make_skill(svc, "good", "Helpful")
        _make_skill(svc, "bad", "Broken")
        tracer.record_skill_loaded("conv-y", 0, "good")
        tracer.record_skill_loaded("conv-y", 0, "bad")

        from app.services import task_judge as tj_mod
        from app.services import skill_miner as miner_mod

        async def fake_judge(self, *, user_query, final_response, loaded_skills, trace):
            return JudgeResult(
                success=False,
                confidence=0.9,
                task_signature="x",
                domain="generic",
                used_skills=loaded_skills,
                failed_skill="bad",
                failure_reason="bad skill misled the agent",
                rationale="x",
            )

        async def fake_maybe_mine(self, **kwargs):
            return None

        monkeypatch.setattr(tj_mod.TaskJudge, "judge", fake_judge)
        monkeypatch.setattr(miner_mod.SkillMiner, "maybe_mine", fake_maybe_mine)

        await run_post_task_evolution(
            conversation_id="conv-y",
            round_idx=0,
            user_query="x",
            final_response="failed",
            judge_model=None,
            svc=svc, log=log, tracer=tracer, siglog=siglog,
        )
        # The "good" skill recovered the agent → counted as success.
        # The "bad" skill takes the blame.
        assert log.get_skill_stats("good")["n_succ"] == 1
        assert log.get_skill_stats("good")["n_fail"] == 0
        assert log.get_skill_stats("bad")["n_succ"] == 0
        assert log.get_skill_stats("bad")["n_fail"] == 1
