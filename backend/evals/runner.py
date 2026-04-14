"""Eval runner — loads cases, executes agents, runs checkers, writes reports.

Key design changes vs v1:

1. **Multi-run**: each case runs N times (default 3) to capture the
   inherent variance of LLM-based systems.  Pass rate becomes a mean +
   std across runs, not a single data point.

2. **Event capture**: every SSE event emitted during workforce execution
   is kept in the ``SingleRun.events`` list.  This is what feeds the
   failure-attribution heuristic.

3. **Failure attribution**: failed runs are tagged with a ``FailureStage``
   (classification / decomposition / agent_execution / …) so reports
   surface *where* the pipeline broke, not just that it broke.

4. **Capability tags**: cases can declare ``capability`` and
   ``difficulty`` so reports can aggregate by dimension.
"""

import asyncio
import json
import logging
import math
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from app.agents.factory import classify_question, create_classifier_agent
from app.models.enums import Status
from app.services.agent_service import (
    build_agent,
    build_model,
    build_workforce,
    agent_chat,
    summarize_workforce_result,
)
from app.services.task_lock import TaskLock
from evals.attribution import FailureStage, attribute_failure, summarize_failures
from evals.checkers import CHECKER_REGISTRY
from evals.judge import llm_judge

logger = logging.getLogger(__name__)

CASES_PATH = Path(__file__).parent / "cases.yaml"
REPORTS_DIR = Path(__file__).parent / "reports"
BASELINES_DIR = Path(__file__).parent / "baselines"

# A case is considered "passed" when at least this fraction of runs pass.
# 2/3 tolerates one flake in three runs while catching persistent failures.
PASS_THRESHOLD = 2 / 3


# ------------------------------------------------------------------
# Result model
# ------------------------------------------------------------------

@dataclass
class SingleRun:
    """One execution of a case."""
    passed_checks: dict[str, bool] = field(default_factory=dict)
    quality_score: Optional[float] = None
    quality_reasoning: str = ""
    latency_s: float = 0.0
    events: list[dict] = field(default_factory=list)
    failure_stage: Optional[str] = None
    error: Optional[str] = None

    @property
    def passed(self) -> bool:
        if self.error is not None:
            return False
        checks = list(self.passed_checks.values())
        return len(checks) > 0 and all(checks)


@dataclass
class EvalResult:
    """Aggregated results for N runs of one case."""
    case_id: str
    description: str = ""
    capability: Optional[str] = None
    difficulty: Optional[str] = None
    runs: list[SingleRun] = field(default_factory=list)

    @property
    def n_runs(self) -> int:
        return len(self.runs)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.runs if r.passed)

    @property
    def pass_rate(self) -> float:
        return self.pass_count / self.n_runs if self.n_runs else 0.0

    @property
    def pass_rate_std(self) -> float:
        """Bernoulli std dev: ``sqrt(p*(1-p)/n)``.

        Note: with n < 10 this is a rough estimate; we surface it anyway
        so readers can see where single-run noise lives.
        """
        p = self.pass_rate
        return math.sqrt(p * (1 - p) / self.n_runs) if self.n_runs else 0.0

    @property
    def passed(self) -> bool:
        # Tolerance guards against float edge cases (e.g. 2/3 vs 0.6667)
        return self.n_runs > 0 and self.pass_rate >= PASS_THRESHOLD - 1e-9

    @property
    def avg_latency(self) -> float:
        return (
            sum(r.latency_s for r in self.runs) / self.n_runs
            if self.n_runs else 0.0
        )

    @property
    def avg_quality(self) -> Optional[float]:
        scores = [r.quality_score for r in self.runs if r.quality_score is not None]
        return sum(scores) / len(scores) if scores else None

    @property
    def dominant_failure_stage(self) -> Optional[str]:
        stages = [r.failure_stage for r in self.runs if r.failure_stage]
        if not stages:
            return None
        return Counter(stages).most_common(1)[0][0]


# ------------------------------------------------------------------
# Single-pass runner
# ------------------------------------------------------------------

async def _run_single_pass(
    case: dict,
    provider: str,
    model_name: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
) -> SingleRun:
    """Execute one pass of a case.  Called ``n_runs`` times per case."""
    case_id = case["id"]
    expected = case.get("expected", {})
    run = SingleRun()
    start = time.time()

    try:
        # ---- Step 1: Classification ----
        model = build_model(provider, model_name, api_key, api_base, stream=False)
        classifier = create_classifier_agent(model)
        classification = await classify_question(classifier, case["input"], [])
        logger.info(f"[EVAL:{case_id}] classification={classification}")

        if "classification" in expected:
            run.passed_checks.update(
                CHECKER_REGISTRY["classification"](
                    expected=expected["classification"],
                    actual_classification=classification,
                )
            )

        # Use the ACTUAL classification to decide the path — this tests
        # the real end-to-end system, not a pre-ordained routing.
        if classification == "simple":
            answer = await _run_simple_path(
                case["input"], provider, model_name, api_key, api_base,
            )
            if "answer_contains" in expected:
                run.passed_checks.update(
                    CHECKER_REGISTRY["answer_contains"](
                        keywords=expected["answer_contains"],
                        answer=answer,
                    )
                )

        else:
            # ---- Complex path: workforce ----
            workdir, activated_agents, events, answer = await _run_workforce_path(
                case["input"], provider, model_name, api_key, api_base,
            )
            run.events = events
            files = expected.get("files", [])

            # Run all declared checkers
            for key, value in expected.items():
                if key in ("classification", "files", "quality_rubric",
                           "agents_used", "answer_contains"):
                    continue
                checker = CHECKER_REGISTRY.get(key)
                if checker:
                    checks = checker(value, workdir=workdir, files=files)
                    run.passed_checks.update(checks)

            if "files" in expected:
                run.passed_checks.update(
                    CHECKER_REGISTRY["files"](
                        expected_files=files, workdir=workdir,
                    )
                )

            if "agents_used" in expected:
                run.passed_checks.update(
                    CHECKER_REGISTRY["agents_used"](
                        expected_agents=expected["agents_used"],
                        activated_agents=activated_agents,
                    )
                )

            if "quality_rubric" in expected:
                file_contents = _collect_file_contents(workdir, files)
                judge_input = f"Answer: {answer[:2000]}\n\nFiles:\n{file_contents}"
                judge_result = await llm_judge(
                    question=case["input"],
                    result=judge_input,
                    rubric=expected["quality_rubric"],
                    provider=provider,
                    model_name=model_name,
                    api_key=api_key,
                    api_base=api_base,
                )
                run.quality_score = judge_result["score"]
                run.quality_reasoning = judge_result["reasoning"]
                run.passed_checks["quality>=70"] = judge_result["score"] >= 70

    except Exception as e:
        logger.error(f"[EVAL:{case_id}] Error: {e}", exc_info=True)
        run.error = str(e)

    run.latency_s = time.time() - start

    # Attribute failure stage (returns None if the run actually passed)
    stage = attribute_failure(run.passed_checks, run.events, run.error)
    run.failure_stage = stage.value if stage else None

    return run


async def run_single_eval(
    case: dict,
    provider: str,
    model_name: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    n_runs: int = 1,
) -> EvalResult:
    """Run a case ``n_runs`` times and return aggregated results."""
    result = EvalResult(
        case_id=case["id"],
        description=case.get("description", ""),
        capability=case.get("capability"),
        difficulty=case.get("difficulty"),
    )

    for i in range(n_runs):
        if n_runs > 1:
            print(f"  Run {i + 1}/{n_runs}...")
        run = await _run_single_pass(
            case, provider, model_name, api_key, api_base,
        )
        result.runs.append(run)

    return result


# ------------------------------------------------------------------
# Execution paths
# ------------------------------------------------------------------

async def _run_simple_path(
    message: str,
    provider: str,
    model_name: str,
    api_key: Optional[str],
    api_base: Optional[str],
) -> str:
    agent = build_agent(
        provider=provider, model_name=model_name,
        api_key=api_key, api_base=api_base,
    )
    full = ""
    async for event in agent_chat(agent, message):
        if event["type"] == "done":
            full = event.get("content", full)
        elif event["type"] == "delta":
            full += event["content"]
    return full


async def _run_workforce_path(
    message: str,
    provider: str,
    model_name: str,
    api_key: Optional[str],
    api_base: Optional[str],
) -> tuple[str, list[str], list[dict], str]:
    """Run the workforce path and capture every SSE event.

    Returns ``(workdir, activated_agents, events, summary_text)``.  The
    full event list is needed by :func:`attribute_failure`.
    """
    task_lock = TaskLock(
        id=f"eval_{int(time.time())}",
        status=Status.classifying,
    )

    workforce = await build_workforce(
        task_lock=task_lock,
        provider=provider,
        model_name=model_name,
        api_key=api_key,
        api_base=api_base,
    )

    activated_agents: list[str] = []
    events: list[dict] = []
    subtask_results: dict = {}

    bg_task = asyncio.create_task(workforce.run(message))

    while True:
        if bg_task.done() and task_lock.queue.empty():
            exc = bg_task.exception()
            if exc:
                raise exc
            break

        try:
            event = await asyncio.wait_for(task_lock.get_event(), timeout=1800)
        except asyncio.TimeoutError:
            bg_task.cancel()
            raise TimeoutError("Workforce timed out (1800s)")

        events.append(event)
        step = event["step"]
        data = event["data"]

        if step == "activate_agent":
            activated_agents.append(data.get("agent_name", ""))
        elif step == "assign_task":
            agent_desc = data.get("assignee_id", "")
            if agent_desc:
                activated_agents.append(agent_desc)
        elif step == "end":
            subtask_results = data.get("subtask_results", {})
            break
        elif step == "error":
            raise RuntimeError(data.get("message", "Workforce error"))

    if not bg_task.done():
        bg_task.cancel()
        try:
            await bg_task
        except asyncio.CancelledError:
            pass

    summary = await summarize_workforce_result(
        subtask_results, message, provider, model_name, api_key, api_base,
    )

    await task_lock.cleanup()
    return task_lock.working_directory, activated_agents, events, summary


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _collect_file_contents(workdir: str, files: list, max_chars: int = 4000) -> str:
    parts = []
    total = 0
    for f in files:
        p = Path(workdir) / f
        if not p.exists():
            parts.append(f"--- {f} (NOT FOUND) ---")
            continue
        content = p.read_text(encoding="utf-8", errors="replace")
        if total + len(content) > max_chars:
            content = content[: max_chars - total] + "\n... (truncated)"
        parts.append(f"--- {f} ---\n{content}")
        total += len(content)
        if total >= max_chars:
            break
    return "\n\n".join(parts)


# ------------------------------------------------------------------
# Run all
# ------------------------------------------------------------------

async def run_all_evals(
    provider: str,
    model_name: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    case_ids: Optional[list[str]] = None,
    capability: Optional[str] = None,
    n_runs: int = 1,
) -> list[EvalResult]:
    """Run all (or selected) eval cases and save a report."""
    cases = yaml.safe_load(CASES_PATH.read_text())
    if case_ids:
        cases = [c for c in cases if c["id"] in case_ids]
        not_found = set(case_ids) - {c["id"] for c in cases}
        if not_found:
            raise ValueError(
                f"Unknown case IDs: {not_found}. "
                f"Use --list to see available cases."
            )

    if capability:
        cases = [c for c in cases if c.get("capability") == capability]

    if not cases:
        raise ValueError("No eval cases to run. Use --list to see available cases.")

    results: list[EvalResult] = []

    for case in cases:
        print(f"\n{'='*60}")
        print(f"Running: {case['id']} — {case.get('description', '')}")
        if case.get("capability"):
            print(f"  capability: {case['capability']} | difficulty: {case.get('difficulty', '?')}")
        print(f"{'='*60}")

        eval_result = await run_single_eval(
            case, provider, model_name, api_key, api_base, n_runs=n_runs,
        )
        results.append(eval_result)

        _print_case_result(eval_result)

    _print_overall_summary(results, n_runs)

    report_path = save_report(
        provider=provider,
        model_name=model_name,
        custom_results=results,
        n_runs=n_runs,
    )
    print(f"\nReport saved: {report_path}")

    return results


def _print_case_result(r: EvalResult):
    status = "PASS" if r.passed else "FAIL"
    n = r.n_runs
    if n > 1:
        print(f"\n  [{status}] {r.case_id}  {r.pass_count}/{n} runs passed "
              f"({r.pass_rate:.0%} ± {r.pass_rate_std:.0%})")
    else:
        print(f"\n  [{status}] {r.case_id}")

    print(f"  Avg latency: {r.avg_latency:.1f}s")
    if r.avg_quality is not None:
        print(f"  Avg quality: {r.avg_quality:.0f}/100")
    if r.dominant_failure_stage:
        print(f"  Failure:     {r.dominant_failure_stage}")

    # Show checks from the last run (representative)
    if r.runs:
        last = r.runs[-1]
        if last.error:
            print(f"  Error:       {last.error[:200]}")
        for check, passed in last.passed_checks.items():
            mark = "+" if passed else "x"
            print(f"    [{mark}] {check}")


def _print_overall_summary(results: list[EvalResult], n_runs: int):
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    avg_pass_rate = (
        sum(r.pass_rate for r in results) / total if total else 0
    )
    quality_scores = [r.avg_quality for r in results if r.avg_quality is not None]
    avg_quality = (
        sum(quality_scores) / len(quality_scores) if quality_scores else None
    )

    print(f"\n{'='*60}")
    print(f"SUMMARY: {passed}/{total} cases fully passed "
          f"(threshold: {PASS_THRESHOLD:.0%} of {n_runs} runs)")
    print(f"Average pass rate: {avg_pass_rate:.0%}")
    if avg_quality is not None:
        print(f"Average quality:   {avg_quality:.0f}/100")

    # Failure breakdown
    stage_counts: dict[FailureStage, int] = {s: 0 for s in FailureStage}
    total_failed_runs = 0
    for r in results:
        for run in r.runs:
            if run.failure_stage:
                try:
                    stage_counts[FailureStage(run.failure_stage)] += 1
                    total_failed_runs += 1
                except ValueError:
                    pass

    if total_failed_runs > 0:
        print(f"\nFailure breakdown ({total_failed_runs} failed runs):")
        for line in summarize_failures(stage_counts, total_failed_runs):
            print(line)

    # Capability breakdown
    capability_results: dict[str, list[EvalResult]] = {}
    for r in results:
        if r.capability:
            capability_results.setdefault(r.capability, []).append(r)

    if capability_results:
        print(f"\nBy capability:")
        for cap, items in sorted(capability_results.items()):
            cap_passed = sum(1 for r in items if r.passed)
            cap_rate = sum(r.pass_rate for r in items) / len(items)
            print(f"  {cap:<28} {cap_passed}/{len(items)} passed, "
                  f"avg pass rate {cap_rate:.0%}")

    print(f"{'='*60}")


def save_report(
    provider: str,
    model_name: str,
    custom_results: Optional[list[EvalResult]] = None,
    gaia_results: Optional[list] = None,
    n_runs: int = 1,
    tag: str = "",
) -> Path:
    """Save a unified JSON report combining custom and/or GAIA results."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "timestamp": datetime.now().isoformat(),
        "provider": provider,
        "model": model_name,
        "n_runs": n_runs,
    }

    if custom_results is not None:
        report["custom"] = _build_custom_section(custom_results)

    if gaia_results is not None:
        total = len(gaia_results)
        correct = sum(1 for r in gaia_results if r.correct)
        accuracy = correct / total if total else 0
        level_breakdown = {}
        for lvl in [1, 2, 3]:
            lvl_items = [r for r in gaia_results if r.level == lvl]
            if lvl_items:
                lvl_correct = sum(1 for r in lvl_items if r.correct)
                level_breakdown[f"level_{lvl}"] = {
                    "total": len(lvl_items),
                    "correct": lvl_correct,
                    "accuracy": round(lvl_correct / len(lvl_items), 3),
                }
        report["gaia"] = {
            "total": total,
            "correct": correct,
            "accuracy": round(accuracy, 3),
            "level_breakdown": level_breakdown,
            "results": [asdict(r) for r in gaia_results],
        }

    suffix = f"_{tag}" if tag else ""
    report_path = REPORTS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}{suffix}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report_path


def _build_custom_section(results: list[EvalResult]) -> dict:
    """Produce the ``custom`` section of the JSON report."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    avg_pass_rate = sum(r.pass_rate for r in results) / total if total else 0
    quality_scores = [r.avg_quality for r in results if r.avg_quality is not None]
    avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else None

    # Failure breakdown
    stage_counts: dict[str, int] = {}
    for r in results:
        for run in r.runs:
            if run.failure_stage:
                stage_counts[run.failure_stage] = stage_counts.get(run.failure_stage, 0) + 1

    # Capability breakdown
    by_capability: dict[str, dict] = {}
    for r in results:
        if not r.capability:
            continue
        bucket = by_capability.setdefault(
            r.capability, {"total": 0, "passed": 0, "pass_rates": []},
        )
        bucket["total"] += 1
        if r.passed:
            bucket["passed"] += 1
        bucket["pass_rates"].append(r.pass_rate)
    for cap, bucket in by_capability.items():
        bucket["avg_pass_rate"] = round(
            sum(bucket["pass_rates"]) / len(bucket["pass_rates"]), 3,
        )
        del bucket["pass_rates"]

    return {
        "total_cases": total,
        "passed_cases": passed,
        "average_pass_rate": round(avg_pass_rate, 3),
        "average_quality": round(avg_quality, 1) if avg_quality is not None else None,
        "failure_breakdown": stage_counts,
        "by_capability": by_capability,
        "results": [asdict(r) for r in results],
    }
