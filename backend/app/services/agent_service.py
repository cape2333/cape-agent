import json
import uuid
import logging
from typing import AsyncGenerator, List, Optional

from camel.agents import ChatAgent
from camel.messages import BaseMessage
from camel.models import ModelFactory
from camel.toolkits import FunctionTool
from camel.types import ModelPlatformType, OpenAIBackendRole, RoleType

logger = logging.getLogger(__name__)

PLATFORM_MAP = {
    "openai": ModelPlatformType.OPENAI,
    "anthropic": ModelPlatformType.ANTHROPIC,
    "gemini": ModelPlatformType.GEMINI,
    "deepseek": ModelPlatformType.DEEPSEEK,
    "groq": ModelPlatformType.GROQ,
    "mistral": ModelPlatformType.MISTRAL,
    "ollama": ModelPlatformType.OLLAMA,
    "minimax": ModelPlatformType.MINIMAX,
}

BROWSER_SYSTEM_PROMPT = """\
You are an autonomous browser automation agent. Your purpose is to take action, \
not to ask questions.

## Core Principles

1. **Bias for Action**: When the user gives you a task, start executing immediately \
using your browser tools. Do NOT ask for clarification, confirmation, or details \
unless you are truly blocked (e.g., login credentials needed, CAPTCHA encountered).

2. **Make Reasonable Decisions**: If the user's request is vague, make sensible \
default choices and proceed. For example:
   - "Post something on Xiaohongshu" → Pick a topic, write content, and post it.
   - "Search for flights" → Go to a travel site, search with reasonable defaults.
   - "Help me order food" → Navigate to a delivery app and start browsing.

3. **Execute, Don't Suggest**: Never respond with a list of steps you "could" take. \
Instead, start doing it. Use browser_visit_page to navigate, browser_click to \
interact, browser_type to fill in forms.

4. **Brief Progress Updates**: Keep text responses very short — just 1-2 sentences \
describing what you're doing now, then call the next browser tool.

## When to Ask the User

ONLY ask the user when you are genuinely stuck and cannot proceed:
- Login is required and you don't have credentials
- A CAPTCHA or verification code appears that needs human input
- The task is fundamentally ambiguous (e.g., "do something" with no context at all)

For everything else: just do it.

## Workflow

1. Immediately call browser_visit_page to navigate to the relevant website
2. Use browser_get_page_snapshot to understand the current page
3. Interact with elements using browser_click, browser_type, browser_select
4. Repeat until the task is complete
5. Report the result briefly when done\
"""

DEFAULT_SYSTEM_PROMPT = "You are a helpful AI assistant."


# ─── Custom Agent with tool event tracking ────────────────────────────────────

class CapeAgent(ChatAgent):
    """ChatAgent subclass that tracks tool execution events.

    Tool events are stored in a list and can be drained by the consumer
    between streaming chunks. This is analogous to eigent's @listen_toolkit
    pattern but simpler — no separate queue/coroutine needed because CAMEL's
    streaming loop naturally pauses during tool execution and resumes after.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tool_events: list = []

    async def _aexecute_tool_from_stream_data(self, tool_call_data):
        """Override streaming-path tool execution to emit events."""
        function_name = tool_call_data["function"]["name"]
        args_str = tool_call_data["function"].get("arguments", "{}")
        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
        except (json.JSONDecodeError, TypeError):
            args = {}

        step_id = str(uuid.uuid4())[:8]
        self._tool_events.append({
            "type": "tool_start",
            "step_id": step_id,
            "tool_name": function_name,
            "tool_args": args,
        })

        result = await super()._aexecute_tool_from_stream_data(tool_call_data)

        result_str = str(result.result)[:500] if result else "no result"
        self._tool_events.append({
            "type": "tool_result",
            "step_id": step_id,
            "tool_name": function_name,
            "tool_result": result_str,
        })

        return result

    async def _aexecute_tool(self, tool_call_request):
        """Override non-streaming-path tool execution to emit events."""
        step_id = str(uuid.uuid4())[:8]
        self._tool_events.append({
            "type": "tool_start",
            "step_id": step_id,
            "tool_name": tool_call_request.tool_name,
            "tool_args": tool_call_request.args,
        })

        result = await super()._aexecute_tool(tool_call_request)

        result_str = str(result.result)[:500] if result else "no result"
        self._tool_events.append({
            "type": "tool_result",
            "step_id": step_id,
            "tool_name": tool_call_request.tool_name,
            "tool_result": result_str,
        })

        return result

    def drain_tool_events(self) -> list:
        """Return and clear any pending tool events."""
        events = self._tool_events[:]
        self._tool_events.clear()
        return events


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_message(role: str, content: str) -> BaseMessage:
    if role == "user":
        return BaseMessage(
            role_name="user", role_type=RoleType.USER,
            content=content, meta_dict={},
        )
    return BaseMessage(
        role_name="assistant", role_type=RoleType.ASSISTANT,
        content=content, meta_dict={},
    )


def build_agent(
    provider: str,
    model_name: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    history: Optional[List[dict]] = None,
    tools: Optional[List[FunctionTool]] = None,
) -> CapeAgent:
    platform = PLATFORM_MAP.get(provider, ModelPlatformType.OPENAI)

    kwargs = {}
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["url"] = api_base

    model = ModelFactory.create(
        model_platform=platform,
        model_type=model_name,
        model_config_dict={"stream": True, "temperature": 0.7},
        **kwargs,
    )

    system_message = BROWSER_SYSTEM_PROMPT if tools else DEFAULT_SYSTEM_PROMPT

    agent = CapeAgent(
        system_message=system_message,
        model=model,
        tools=tools or [],
        stream_accumulate=False,
    )

    # Replay history into agent memory
    if history:
        for msg in history:
            role_enum = OpenAIBackendRole.USER if msg["role"] == "user" else OpenAIBackendRole.ASSISTANT
            agent.update_memory(
                message=_make_message(msg["role"], msg["content"]),
                role=role_enum,
            )

    return agent


# ─── Chat functions ───────────────────────────────────────────────────────────

async def agent_chat(
    agent: CapeAgent,
    user_message: str,
) -> AsyncGenerator[dict, None]:
    """Run agent with tool calling support. Yields structured events.

    The agent uses stream=True always. CAMEL's internal streaming loop
    handles tool execution automatically:
      stream text → detect tool call → execute tool → loop → stream more text

    Tool events are captured by CapeAgent's overridden _aexecute_tool* methods
    and drained between streaming chunks.

    Events:
    - {"type": "delta", "content": "..."} — text chunk
    - {"type": "tool_start", "step_id": "...", "tool_name": "...", "tool_args": {...}}
    - {"type": "tool_result", "step_id": "...", "tool_name": "...", "tool_result": "..."}
    - {"type": "done", "content": "..."} — final full text
    """
    response = await agent.astep(user_message)
    full_content = ""

    if hasattr(response, "__aiter__"):
        # Streaming response — iterate chunks
        async for partial in response:
            # Drain any tool events that occurred during tool execution
            for event in agent.drain_tool_events():
                yield event

            delta = partial.msg.content if partial.msg else ""
            if delta:
                full_content += delta
                yield {"type": "delta", "content": delta}
    else:
        # Non-streaming fallback
        if response.msgs:
            full_content = response.msgs[0].content
            yield {"type": "delta", "content": full_content}

    # Final drain — catch any tool events from the last iteration
    for event in agent.drain_tool_events():
        yield event

    yield {"type": "done", "content": full_content}
