"""A/B comparison — did the last change actually improve the agent?

Workflow:

    # Baseline the current behaviour (e.g. before a prompt change)
    python -m evals --runs 3 --save-baseline pre_refactor

    # Hack on prompts / agents / router …

    # Re-run and compare
    python -m evals --runs 3 --compare-to pre_refactor

Reports surface per-case deltas and a McNemar significance test so the
question "did this change help?" has a numeric answer rather than vibes.

Design notes:

* A baseline is a JSON snapshot of ``EvalResult`` objects plus provider /
  model metadata — just enough to re-hydrate and diff.  We don't store
  the full SSE event stream; it bloats the file and isn't needed for the
  comparison.
* McNemar's test is the right fit for paired binary outcomes on the same
  cases.  With small N we use the exact binomial test (``scipy.stats``)
  rather than the chi-square approximation.
* "passed" here means the case-level ``EvalResult.passed`` (at least
  ``PASS_THRESHOLD`` of runs pass), not individual-run success.  Cases
  are the unit of comparison; runs are the unit of variance.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from scipy import stats

from evals.runner import BASELINES_DIR, EvalResult, SingleRun

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Persistence
# ------------------------------------------------------------------

def save_baseline(
    results: list[EvalResult],
    tag: str,
    provider: str,
    model_name: str,
    n_runs: int,
) -> Path:
    """Snapshot ``results`` to ``baselines/<tag>.json``."""
    if not tag:
        raise ValueError("Baseline tag cannot be empty.")
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)

    payload = {
        "tag": tag,
        "timestamp": datetime.now().isoformat(),
        "provider": provider,
        "model": model_name,
        "n_runs": n_runs,
        "results": [_serialize_result(r) for r in results],
    }

    path = BASELINES_DIR / f"{tag}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path


def load_baseline(tag: str) -> dict:
    """Load a baseline snapshot and re-hydrate ``EvalResult`` objects.

    Returns a dict with keys ``tag``, ``timestamp``, ``provider``,
    ``model``, ``n_runs``, ``results`` (list[EvalResult]).
    """
    path = BASELINES_DIR / f"{tag}.json"
    if not path.exists():
        available = sorted(p.stem for p in BASELINES_DIR.glob("*.json"))
        raise FileNotFoundError(
            f"Baseline '{tag}' not found at {path}.\n"
            f"Available baselines: {available or '(none)'}"
        )

    payload = json.loads(path.read_text())
    payload["results"] = [
        _deserialize_result(r) for r in payload.get("results", [])
    ]
    return payload


def _serialize_result(r: EvalResult) -> dict:
    """Compact form: drop ``events`` (noisy) but keep checks + error."""
    runs = []
    for run in r.runs:
        runs.append({
            "passed_checks": run.passed_checks,
            "quality_score": run.quality_score,
            "latency_s": run.latency_s,
            "failure_stage": run.failure_stage,
            "error": run.error,
        })
    return {
        "case_id": r.case_id,
        "description": r.description,
        "capability": r.capability,
        "difficulty": r.difficulty,
        "runs": runs,
    }


def _deserialize_result(data: dict) -> EvalResult:
    runs = [
        SingleRun(
            passed_checks=r.get("passed_checks", {}),
            quality_score=r.get("quality_score"),
            latency_s=r.get("latency_s", 0.0),
            failure_stage=r.get("failure_stage"),
            error=r.get("error"),
        )
        for r in data.get("runs", [])
    ]
    return EvalResult(
        case_id=data["case_id"],
        description=data.get("description", ""),
        capability=data.get("capability"),
        difficulty=data.get("difficulty"),
        runs=runs,
    )


# ------------------------------------------------------------------
# Comparison
# ------------------------------------------------------------------

@dataclass
class CaseDiff:
    case_id: str
    capability: Optional[str]
    baseline_pass_rate: float
    current_pass_rate: float
    baseline_passed: bool
    current_passed: bool
    delta_pass_rate: float
    baseline_latency: float
    current_latency: float
    classification: str  # improved | regressed | unchanged | new | removed


@dataclass
class ComparisonReport:
    baseline_tag: str
    baseline_timestamp: str
    baseline_model: str
    current_model: str
    case_diffs: list[CaseDiff] = field(default_factory=list)
    mcnemar_p_value: Optional[float] = None
    mcnemar_improvements: int = 0
    mcnemar_regressions: int = 0
    mcnemar_verdict: str = ""

    @property
    def n_improved(self) -> int:
        return sum(1 for d in self.case_diffs if d.classification == "improved")

    @property
    def n_regressed(self) -> int:
        return sum(1 for d in self.case_diffs if d.classification == "regressed")

    @property
    def n_unchanged(self) -> int:
        return sum(1 for d in self.case_diffs if d.classification == "unchanged")

    @property
    def n_new(self) -> int:
        return sum(1 for d in self.case_diffs if d.classification == "new")

    @property
    def n_removed(self) -> int:
        return sum(1 for d in self.case_diffs if d.classification == "removed")


def compare_reports(
    baseline: dict,
    current: list[EvalResult],
) -> ComparisonReport:
    """Diff ``current`` against a loaded ``baseline`` snapshot."""
    baseline_results: list[EvalResult] = baseline["results"]
    baseline_by_id = {r.case_id: r for r in baseline_results}
    current_by_id = {r.case_id: r for r in current}

    diffs: list[CaseDiff] = []

    # Cases present in baseline
    for case_id, b in baseline_by_id.items():
        c = current_by_id.get(case_id)
        if c is None:
            diffs.append(CaseDiff(
                case_id=case_id,
                capability=b.capability,
                baseline_pass_rate=b.pass_rate,
                current_pass_rate=0.0,
                baseline_passed=b.passed,
                current_passed=False,
                delta_pass_rate=-b.pass_rate,
                baseline_latency=b.avg_latency,
                current_latency=0.0,
                classification="removed",
            ))
            continue

        delta = c.pass_rate - b.pass_rate
        if c.passed and not b.passed:
            cls = "improved"
        elif b.passed and not c.passed:
            cls = "regressed"
        elif delta > 1e-9:
            cls = "improved"
        elif delta < -1e-9:
            cls = "regressed"
        else:
            cls = "unchanged"

        diffs.append(CaseDiff(
            case_id=case_id,
            capability=c.capability or b.capability,
            baseline_pass_rate=b.pass_rate,
            current_pass_rate=c.pass_rate,
            baseline_passed=b.passed,
            current_passed=c.passed,
            delta_pass_rate=delta,
            baseline_latency=b.avg_latency,
            current_latency=c.avg_latency,
            classification=cls,
        ))

    # Cases only in current
    for case_id, c in current_by_id.items():
        if case_id in baseline_by_id:
            continue
        diffs.append(CaseDiff(
            case_id=case_id,
            capability=c.capability,
            baseline_pass_rate=0.0,
            current_pass_rate=c.pass_rate,
            baseline_passed=False,
            current_passed=c.passed,
            delta_pass_rate=c.pass_rate,
            baseline_latency=0.0,
            current_latency=c.avg_latency,
            classification="new",
        ))

    # McNemar on paired cases (exclude new/removed)
    improvements = sum(
        1 for d in diffs
        if d.classification == "improved" and not d.baseline_passed and d.current_passed
    )
    regressions = sum(
        1 for d in diffs
        if d.classification == "regressed" and d.baseline_passed and not d.current_passed
    )
    p_value, verdict = _mcnemar(improvements, regressions)

    return ComparisonReport(
        baseline_tag=baseline.get("tag", "?"),
        baseline_timestamp=baseline.get("timestamp", "?"),
        baseline_model=f"{baseline.get('provider', '?')}/{baseline.get('model', '?')}",
        current_model="(current run)",
        case_diffs=sorted(diffs, key=lambda d: (d.classification, d.case_id)),
        mcnemar_p_value=p_value,
        mcnemar_improvements=improvements,
        mcnemar_regressions=regressions,
        mcnemar_verdict=verdict,
    )


def _mcnemar(b: int, c: int, alpha: float = 0.05) -> tuple[Optional[float], str]:
    """Exact McNemar's test for paired binary outcomes.

    ``b`` = cases that flipped from pass→fail (regressions); ``c`` =
    cases that flipped from fail→pass (improvements).  We use the exact
    binomial test instead of the chi-square approximation so small N is
    handled correctly (statsmodels does the same thing under the hood).
    """
    n = b + c
    if n == 0:
        return None, "no flipped cases — nothing to test"

    result = stats.binomtest(min(b, c), n, p=0.5, alternative="two-sided")
    p = float(result.pvalue)

    if p >= alpha:
        verdict = f"no significant change (p={p:.3f}, α={alpha})"
    elif c > b:
        verdict = f"significant IMPROVEMENT (p={p:.3f}, α={alpha})"
    else:
        verdict = f"significant REGRESSION (p={p:.3f}, α={alpha})"
    return p, verdict


# ------------------------------------------------------------------
# Pretty printing
# ------------------------------------------------------------------

def format_comparison(report: ComparisonReport) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append(f"A/B Comparison vs baseline '{report.baseline_tag}' "
                 f"({report.baseline_timestamp[:19]})")
    lines.append(f"Baseline model: {report.baseline_model}")
    lines.append("=" * 70)

    lines.append(
        f"Improved:  {report.n_improved:>3}   "
        f"Regressed: {report.n_regressed:>3}   "
        f"Unchanged: {report.n_unchanged:>3}   "
        f"New:       {report.n_new:>3}   "
        f"Removed:   {report.n_removed:>3}"
    )
    lines.append("")

    # Significance verdict
    if report.mcnemar_p_value is not None:
        lines.append(
            f"McNemar: {report.mcnemar_improvements} improvements vs "
            f"{report.mcnemar_regressions} regressions on paired cases"
        )
        lines.append(f"  -> {report.mcnemar_verdict}")
    else:
        lines.append(f"McNemar: {report.mcnemar_verdict}")
    lines.append("")

    # Per-case details for non-unchanged
    notable = [d for d in report.case_diffs if d.classification != "unchanged"]
    if notable:
        lines.append("Notable cases:")
        lines.append(f"  {'case':<35} {'cap':<22} {'Δ':>8}   base -> now")
        lines.append(f"  {'-'*35} {'-'*22} {'-'*8}   {'-'*12}")
        for d in notable:
            marker = {
                "improved":  "+",
                "regressed": "x",
                "new":       "*",
                "removed":   "-",
            }.get(d.classification, " ")
            delta_str = f"{d.delta_pass_rate:+.0%}"
            rates = f"{d.baseline_pass_rate:.0%} -> {d.current_pass_rate:.0%}"
            cap = d.capability or ""
            lines.append(
                f"  [{marker}] {d.case_id:<31} {cap:<22} {delta_str:>8}   {rates}"
            )
    lines.append("=" * 70)
    return "\n".join(lines)


def save_comparison(
    report: ComparisonReport,
    reports_dir: Path,
) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / (
        f"comparison_{report.baseline_tag}_"
        f"{datetime.now():%Y%m%d_%H%M%S}.json"
    )
    payload = {
        "baseline_tag": report.baseline_tag,
        "baseline_timestamp": report.baseline_timestamp,
        "baseline_model": report.baseline_model,
        "mcnemar_p_value": report.mcnemar_p_value,
        "mcnemar_improvements": report.mcnemar_improvements,
        "mcnemar_regressions": report.mcnemar_regressions,
        "mcnemar_verdict": report.mcnemar_verdict,
        "summary": {
            "improved": report.n_improved,
            "regressed": report.n_regressed,
            "unchanged": report.n_unchanged,
            "new": report.n_new,
            "removed": report.n_removed,
        },
        "case_diffs": [asdict(d) for d in report.case_diffs],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path
