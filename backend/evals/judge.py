"""LLM-as-judge for subjective quality evaluation."""

import json
import logging
from typing import Optional

from camel.agents import ChatAgent

from app.services.agent_service import build_model

logger = logging.getLogger(__name__)

JUDGE_SYSTEM = "You are a strict but fair evaluator of AI agent outputs."

JUDGE_PROMPT = """\
Evaluate the AI agent's output against the given criteria.

**User's original request:**
{question}

**Agent's output (files and content):**
{result}

**Evaluation criteria:**
{rubric}

Score from 0 to 100, where:
- 0-30: Missing most requirements
- 31-60: Partially complete, significant gaps
- 61-80: Mostly complete with minor issues
- 81-100: Fully meets or exceeds requirements

Respond with JSON only, no other text:
{{"score": <0-100>, "reasoning": "<2-3 sentences explaining the score>"}}
"""


async def llm_judge(
    question: str,
    result: str,
    rubric: str,
    provider: str,
    model_name: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
) -> dict:
    """Run LLM-as-judge evaluation.

    Returns ``{"score": int, "reasoning": str}`` on success, or
    ``{"score": 0, "reasoning": "error message"}`` on failure.
    """
    try:
        model = build_model(
            provider, model_name, api_key, api_base, stream=False,
        )
        agent = ChatAgent(system_message=JUDGE_SYSTEM, model=model)

        prompt = JUDGE_PROMPT.format(
            question=question,
            result=result[:6000],
            rubric=rubric,
        )

        response = await agent.astep(prompt)

        content = ""
        if hasattr(response, "msg") and response.msg:
            content = response.msg.content or ""
        elif hasattr(response, "msgs") and response.msgs:
            content = response.msgs[0].content or ""

        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        parsed = json.loads(content)
        score = int(parsed.get("score", 0))
        reasoning = parsed.get("reasoning", "")

        logger.info(f"[JUDGE] score={score}, reasoning={reasoning[:100]}")
        return {"score": score, "reasoning": reasoning}

    except Exception as e:
        logger.error(f"[JUDGE] Failed: {e}")
        return {"score": 0, "reasoning": f"Judge error: {e}"}
