"""Post-task background review that converts pending insights into skills.

TODO(skill_evolved): the frontend store already handles a `skill_evolved`
SSE event but no backend path emits one. By design, this reviewer runs
AFTER the chat SSE stream has closed (`yield sse_json("end", ...)`),
so there is no open channel left to push progress on. Delivering evolution
events requires a second channel — a per-conversation notification SSE
endpoint or a WebSocket the frontend holds open across chat rounds.
Tracked as future work; not addressed here.
"""

from __future__ import annotations

import logging
from typing import Optional

from camel.agents import ChatAgent
from camel.toolkits import FunctionTool

from app.services.skill_service import SkillService, skill_service
from app.services.skill_logger import SkillLogger, skill_logger
from app.toolkits.skill_toolkit import SkillToolkit

logger = logging.getLogger(__name__)

REVIEW_PROMPT_TEMPLATE = """\
You are reviewing task execution insights to maintain the skill library.

## Task Summary
{task_summary}

## Pending Insights
{insights_text}

## Existing Skills
{existing_skills_text}

For each insight, decide:
1. If it improves an existing skill -> use skill_manage(action="patch", name="...", old_string="...", new_string="...")
2. If it's a new reusable approach -> use skill_manage(action="create", name="...", content="...")
3. If it's too specific or trivial -> skip it

Only save knowledge that will help future tasks. Be selective.
When creating a new skill, use this SKILL.md format:

---
name: skill-name
description: one-line description
agent_type: browser|developer|document
version: 1
enabled: true
created_by: agent
created_at: ''
updated_at: ''
tags: []
---

## Trigger Conditions
When to use this skill.

## Steps
1. Step one
2. Step two

## Pitfalls
- Known issues

## Verification
- How to confirm success
"""


async def review_insights(
    conversation_id: str,
    task_summary: str,
    model,
    svc: SkillService | None = None,
    log: SkillLogger | None = None,
) -> None:
    svc = svc or skill_service
    log = log or skill_logger

    insights = log.read_pending_insights(conversation_id)
    if not insights:
        return

    agent_types = list({i["agent_type"] for i in insights})
    existing = svc.list_skills()
    existing_for_types = [s for s in existing if s.agent_type in agent_types]

    insights_text = "\n".join(
        f"{i+1}. [{ins['agent_type']}] {ins['summary']}"
        + (f" (context: {ins['context']})" if ins.get("context") else "")
        for i, ins in enumerate(insights)
    )
    existing_skills_text = "\n".join(
        f"- {s.name} ({s.agent_type}): {s.description}"
        for s in existing_for_types
    ) or "(none)"

    prompt = REVIEW_PROMPT_TEMPLATE.format(
        task_summary=task_summary,
        insights_text=insights_text,
        existing_skills_text=existing_skills_text,
    )

    toolkit = SkillToolkit(
        agent_type=agent_types[0] if agent_types else "browser",
        skill_service=svc,
        skill_logger=log,
        conversation_id=conversation_id,
    )

    reviewer = ChatAgent(
        system_message="You are a skill librarian. Use the provided tools to create or update skills based on insights.",
        model=model,
        tools=toolkit.get_tools(),
    )

    try:
        await reviewer.astep(prompt)
    except Exception as e:
        # Keep insights for the next attempt so data isn't lost on a
        # transient LLM / network failure.
        logger.warning(
            f"Skill review failed for conversation {conversation_id}; "
            f"insights retained for retry: {e}"
        )
        return

    log.clear_insights(conversation_id)
    logger.info(f"Skill review completed for conversation {conversation_id}")
