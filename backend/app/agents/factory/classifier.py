import json
import logging

from camel.agents import ChatAgent
from camel.messages import BaseMessage

logger = logging.getLogger(__name__)

CLASSIFIER_PROMPT = """\
You are a question classifier. Analyze the user's message and determine if it \
is a SIMPLE question or a COMPLEX task.

SIMPLE: Direct Q&A, greetings, factual questions, opinion requests, \
explanations, translations, math calculations. These can be answered \
directly without tools.

COMPLEX: Multi-step tasks requiring web browsing, code execution, \
file creation, research across multiple sources, document generation, \
or any task that benefits from specialized agents working together.

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
