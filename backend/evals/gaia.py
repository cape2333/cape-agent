"""GAIA benchmark integration.

GAIA (General AI Assistants) is a public benchmark for AI agents that
require multi-step reasoning, tool use, and web browsing.  Each question
has a short ground-truth answer (a number, name, date, …) so evaluation
is a simple string match — no LLM-as-judge needed.

Dataset: https://huggingface.co/datasets/gaia-benchmark/GAIA
Paper:   https://arxiv.org/abs/2311.12983

Prerequisites:
    1. ``pip install datasets``  (already in camel-ai[all])
    2. Accept the dataset licence on HuggingFace:
       https://huggingface.co/datasets/gaia-benchmark/GAIA
    3. ``huggingface-cli login`` or set HF_TOKEN in .env
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from camel.agents import ChatAgent

from app.services.agent_service import build_model

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Answer normalization (follows GAIA official eval logic)
# ------------------------------------------------------------------

def normalize_answer(answer: str) -> str:
    """Normalize an answer string for comparison.

    Mirrors the GAIA leaderboard's scoring: lowercased, stripped of
    punctuation and extra whitespace.
    """
    text = answer.lower().strip()
    # Remove trailing period / punctuation
    text = text.rstrip(".,;:!?")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def answers_match(predicted: str, expected: str) -> bool:
    """Check if *predicted* matches *expected* after normalization.

    Uses exact match, numeric equality, and word-boundary containment
    (not naive substring) to avoid false positives like "3" in "235".
    """
    norm_pred = normalize_answer(predicted)
    norm_exp = normalize_answer(expected)

    if not norm_pred or not norm_exp:
        return False

    # Exact match
    if norm_pred == norm_exp:
        return True

    # Numeric match (e.g. "3.0" vs "3")
    try:
        if float(norm_pred) == float(norm_exp):
            return True
    except ValueError:
        pass

    # Word-boundary containment — prevents "3" matching "235"
    # Only for short expected answers (likely a single value)
    if len(norm_exp) <= 50:
        pattern = r"(?<!\w)" + re.escape(norm_exp) + r"(?!\w)"
        if re.search(pattern, norm_pred):
            return True

    return False


# ------------------------------------------------------------------
# Answer extraction from verbose agent output
# ------------------------------------------------------------------

EXTRACT_PROMPT = """\
A question was asked and an AI agent produced a detailed response.
Extract ONLY the final, concise answer from the response.

Rules:
- Return ONLY the answer value itself (a number, name, date, etc.)
- Do NOT include explanations, units, or extra words
- If the response contains multiple possible answers, pick the most
  directly stated one
- If no clear answer is found, return "UNKNOWN"

Question: {question}

Agent's response:
{response}

Final answer (concise, no explanation):"""


async def extract_answer(
    question: str,
    response: str,
    provider: str,
    model_name: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
) -> str:
    """Use a cheap LLM call to extract a concise answer from verbose output."""
    try:
        model = build_model(
            provider, model_name, api_key, api_base, stream=False,
        )
        agent = ChatAgent(
            system_message="You extract concise answers. Reply with ONLY the answer.",
            model=model,
        )
        prompt = EXTRACT_PROMPT.format(
            question=question,
            response=response[:4000],
        )
        result = await agent.astep(prompt)

        content = ""
        if hasattr(result, "msg") and result.msg:
            content = result.msg.content or ""
        elif hasattr(result, "msgs") and result.msgs:
            content = result.msgs[0].content or ""

        return content.strip()
    except Exception as e:
        logger.error(f"[GAIA] Answer extraction failed: {e}")
        return ""


# ------------------------------------------------------------------
# Result model
# ------------------------------------------------------------------

@dataclass
class GaiaResult:
    task_id: str
    level: int
    question: str
    expected_answer: str
    predicted_answer: str
    raw_response: str
    correct: bool
    latency_s: float
    error: Optional[str] = None


# ------------------------------------------------------------------
# Load dataset
# ------------------------------------------------------------------

def load_gaia_dataset(
    level: Optional[int] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    """Load GAIA validation set from HuggingFace.

    Raises a clear error if the user hasn't authenticated or accepted
    the dataset licence.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        raise RuntimeError(
            "Install the 'datasets' library: pip install datasets"
        )

    try:
        ds = load_dataset(
            "gaia-benchmark/GAIA",
            "2023_all",
            split="validation",
            trust_remote_code=True,
        )
    except Exception as e:
        error_msg = str(e)
        if "gated" in error_msg or "authenticated" in error_msg:
            raise RuntimeError(
                "GAIA is a gated dataset. To use it:\n"
                "  1. Go to https://huggingface.co/datasets/gaia-benchmark/GAIA\n"
                "  2. Accept the licence agreement\n"
                "  3. Run: huggingface-cli login\n"
                "     Or set HF_TOKEN in your .env file"
            ) from e
        raise

    cases = list(ds)

    # Filter by level
    if level is not None:
        cases = [c for c in cases if c["Level"] == level]

    # Skip cases that require file attachments (we don't support those yet)
    cases = [c for c in cases if not c.get("file_name")]

    # Limit
    if limit is not None:
        cases = cases[:limit]

    logger.info(
        f"[GAIA] Loaded {len(cases)} questions"
        + (f" (level={level})" if level else "")
    )
    return cases


# ------------------------------------------------------------------
# Runner
# ------------------------------------------------------------------

async def run_gaia_eval(
    provider: str,
    model_name: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    level: Optional[int] = None,
    limit: Optional[int] = 10,
) -> list[GaiaResult]:
    """Run GAIA benchmark evaluation."""
    from evals.runner import _run_workforce_path

    cases = load_gaia_dataset(level=level, limit=limit)

    if not cases:
        print("No GAIA cases to run.")
        return []

    results: list[GaiaResult] = []

    for i, case in enumerate(cases, 1):
        question = case["Question"]
        expected = case["Final answer"]
        case_level = case["Level"]
        task_id = case.get("task_id", f"gaia_{i}")

        print(f"\n{'='*60}")
        print(f"[{i}/{len(cases)}] GAIA Level {case_level}: {question[:80]}...")
        print(f"Expected answer: {expected}")
        print(f"{'='*60}")

        start = time.time()
        error = None
        raw_response = ""
        predicted = ""

        try:
            # Run through workforce (GAIA tasks are complex by design)
            _workdir, _agents, raw_response = await _run_workforce_path(
                question, provider, model_name, api_key, api_base,
            )

            # Extract concise answer from verbose response
            predicted = await extract_answer(
                question, raw_response,
                provider, model_name, api_key, api_base,
            )
        except Exception as e:
            logger.error(f"[GAIA] Task {task_id} failed: {e}", exc_info=True)
            error = str(e)

        elapsed = time.time() - start
        correct = answers_match(predicted, expected) if not error else False

        result = GaiaResult(
            task_id=task_id,
            level=case_level,
            question=question,
            expected_answer=expected,
            predicted_answer=predicted,
            raw_response=raw_response[:2000],
            correct=correct,
            latency_s=elapsed,
            error=error,
        )
        results.append(result)

        status = "CORRECT" if correct else "WRONG"
        print(f"\n  [{status}] Predicted: {predicted}")
        print(f"  Expected:  {expected}")
        print(f"  Latency:   {elapsed:.1f}s")
        if error:
            print(f"  Error:     {error[:150]}")

    # Summary
    total = len(results)
    correct_count = sum(1 for r in results if r.correct)
    accuracy = correct_count / total if total else 0

    print(f"\n{'='*60}")
    print(f"GAIA RESULTS: {correct_count}/{total} correct ({accuracy:.0%})")
    if level is None:
        for lvl in [1, 2, 3]:
            lvl_results = [r for r in results if r.level == lvl]
            if lvl_results:
                lvl_correct = sum(1 for r in lvl_results if r.correct)
                print(f"  Level {lvl}: {lvl_correct}/{len(lvl_results)} ({lvl_correct/len(lvl_results):.0%})")
    print(f"{'='*60}")

    return results
