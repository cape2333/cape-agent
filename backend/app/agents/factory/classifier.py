import json
import logging

from camel.agents import ChatAgent
from camel.messages import BaseMessage

logger = logging.getLogger(__name__)

CLASSIFIER_PROMPT = """\
You are a question classifier. Analyze the user's message and determine if it \
is a SIMPLE question or a COMPLEX task.

SIMPLE: Direct Q&A, greetings, factual questions, opinion requests, \
explanations, translations, math calculations, casual conversation. \
These can be answered directly without any tools.

COMPLEX: ANY task that involves or implies:
- Opening a browser, visiting a website, navigating to a URL
- Web browsing, web research, searching online
- Code execution, running commands, installing packages
- File creation, document generation, writing to disk
- Research across multiple sources
- Any multi-step task that benefits from specialized agents
- Any request that requires tools (browser, terminal, file system)

When in doubt, classify as COMPLEX. It is better to use the multi-agent \
system for a simple task than to fail on a complex one.

Respond with ONLY a JSON object:
{"type": "simple", "reason": "brief reason"}
or
{"type": "complex", "reason": "brief reason"}
"""


def create_classifier_agent(model) -> ChatAgent:
    return ChatAgent(
        system_message=BaseMessage.make_assistant_message(
            role_name="Classifier",
            content=CLASSIFIER_PROMPT,
        ),
        model=model,
    )


async def classify_question(
    agent: ChatAgent, message: str, history: list
) -> str:
    """Returns 'simple' or 'complex'."""
    try:
        response = await agent.astep(message)
        content = ""

        if hasattr(response, "msg") and response.msg:
            content = response.msg.content or ""
        elif hasattr(response, "msgs") and response.msgs:
            content = response.msgs[0].content or ""

        logger.info(f"Classifier raw response: {content[:200]}")

        # Parse JSON response
        # Strip markdown code fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = json.loads(content)
        classification = result.get("type", "simple")
        logger.info(
            f"Classification: {classification} - {result.get('reason', '')}"
        )
        return classification

    except Exception as e:
        logger.warning(f"Classification failed, defaulting to simple: {e}")
        return "simple"
