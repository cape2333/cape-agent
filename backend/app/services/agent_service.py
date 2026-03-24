# backend/app/services/agent_service.py
import logging
import os
import tempfile
from typing import AsyncGenerator, List, Optional

from camel.agents import ChatAgent
from camel.messages import BaseMessage
from camel.models import ModelFactory
from camel.toolkits import FunctionTool
from camel.types import ModelPlatformType, OpenAIBackendRole, RoleType

from app.agents.workforce import CapeWorkforce
from app.agents.factory import (
    create_browser_agent,
    create_developer_agent,
    create_document_agent,
)
from app.services.browser_service import browser_service
from app.services.task_lock import TaskLock

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

# Maps provider name to the env var CAMEL expects for API keys
PROVIDER_ENV_KEY = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}

DEFAULT_SYSTEM_PROMPT = "You are a helpful AI assistant."


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


def build_model(
    provider: str,
    model_name: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    *,
    stream: bool = True,
):
    """Create a CAMEL model backend."""
    platform = PLATFORM_MAP.get(provider, ModelPlatformType.OPENAI)
    kwargs = {}
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["url"] = api_base

    return ModelFactory.create(
        model_platform=platform,
        model_type=model_name,
        model_config_dict={"stream": stream, "temperature": 0.7},
        **kwargs,
    )


def build_agent(
    provider: str,
    model_name: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    history: Optional[List[dict]] = None,
    tools: Optional[List[FunctionTool]] = None,
) -> ChatAgent:
    """Build a simple ChatAgent for the simple path (no workforce)."""
    model = build_model(
        provider,
        model_name,
        api_key,
        api_base,
        stream=True,
    )

    agent = ChatAgent(
        system_message=DEFAULT_SYSTEM_PROMPT,
        model=model,
        tools=tools or [],
    )

    if history:
        for msg in history:
            role_enum = (
                OpenAIBackendRole.USER
                if msg["role"] == "user"
                else OpenAIBackendRole.ASSISTANT
            )
            agent.update_memory(
                message=_make_message(msg["role"], msg["content"]),
                role=role_enum,
            )

    return agent


async def agent_chat(
    agent: ChatAgent,
    user_message: str,
) -> AsyncGenerator[dict, None]:
    """Simple path streaming. Yields {"type": "delta"/"done", ...} events."""
    response = await agent.astep(user_message)
    full_content = ""

    if hasattr(response, "__aiter__"):
        prev_content = ""
        async for partial in response:
            accumulated = partial.msg.content if partial.msg else ""
            if accumulated and len(accumulated) > len(prev_content):
                delta = accumulated[len(prev_content):]
                prev_content = accumulated
                full_content = accumulated
                yield {"type": "delta", "content": delta}
    else:
        if response.msgs:
            full_content = response.msgs[0].content
            yield {"type": "delta", "content": full_content}

    yield {"type": "done", "content": full_content}


async def summarize_workforce_result(
    subtask_results: dict,
    original_question: str,
    provider: str,
    model_name: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
) -> str:
    """Summarize workforce subtask results into a user-friendly response.

    Args:
        subtask_results: dict mapping task_id to {"result": str}
            collected from TaskCompletedEvent callbacks.
    """
    if not subtask_results:
        logger.warning("[SUMMARY] No subtask results to summarize")
        return "Task completed."

    results = list(subtask_results.values())
    logger.info(
        f"[SUMMARY] Summarizing {len(results)} subtask result(s), "
        f"task_ids={list(subtask_results.keys())}"
    )

    # Single subtask: return its result directly
    if len(results) == 1:
        return results[0].get("result", "") or "Task completed."

    # Multiple subtasks: use LLM to create a cohesive summary
    try:
        platform = PLATFORM_MAP.get(provider, ModelPlatformType.OPENAI)
        model_kwargs = {}
        if api_key:
            model_kwargs["api_key"] = api_key
        if api_base:
            model_kwargs["url"] = api_base
        summary_model = ModelFactory.create(
            model_platform=platform,
            model_type=model_name,
            model_config_dict={"stream": False, "temperature": 0.7},
            **model_kwargs,
        )
        summary_agent = ChatAgent(
            system_message="You are a professional summarizer.",
            model=summary_model,
        )

        subtasks_info = ""
        for i, (task_id, info) in enumerate(subtask_results.items(), 1):
            result_text = info.get("result", "") or "No result"
            # Aggressive truncation to stay within context limits
            if len(result_text) > 2000:
                result_text = result_text[:2000] + "\n... (truncated)"
            subtasks_info += f"\n**Subtask {i}** ({task_id})\n"
            subtasks_info += f"Result: {result_text}\n"
            subtasks_info += "---\n"

        prompt = (
            f"Summarize the results of the following subtasks into a clear, "
            f"complete response for the user.\n\n"
            f"User's original question: {original_question}\n\n"
            f"Subtask results:\n{subtasks_info}\n"
            f"Instructions:\n"
            f"1. Provide a concise but complete summary of what was accomplished\n"
            f"2. Highlight key findings or outputs from each subtask\n"
            f"3. Mention any files created or important actions taken\n"
            f"4. Use markdown formatting for clarity\n"
            f"5. Go straight to results - don't repeat the task description\n"
            f"6. If a subtask produced a document or structured content, "
            f"include the key parts in your response"
        )

        logger.info(f"[SUMMARY] Sending prompt ({len(prompt)} chars) to LLM")
        response = await summary_agent.astep(prompt)
        if response.msgs:
            logger.info("[SUMMARY] LLM summary generated successfully")
            return response.msgs[0].content
    except Exception as e:
        logger.error(f"[SUMMARY] Failed to generate workforce summary: {e}")

    # Fallback: return the last subtask result (usually the final deliverable)
    last_result = results[-1].get("result", "")
    if last_result:
        logger.info("[SUMMARY] Using last subtask result as fallback")
        return last_result
    return "Task completed."


async def build_workforce(
    task_lock: TaskLock,
    provider: str,
    model_name: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
) -> CapeWorkforce:
    """Build a CapeWorkforce with browser, developer, and document agents."""
    # Set API key as env var so CAMEL's internal recovery strategy can use it
    if api_key:
        env_key = PROVIDER_ENV_KEY.get(provider)
        if env_key:
            os.environ[env_key] = api_key

    model = build_model(
        provider,
        model_name,
        api_key,
        api_base,
        stream=False,
    )

    working_dir = tempfile.mkdtemp(prefix=f"cape_{task_lock.id[:8]}_")
    task_lock.working_directory = working_dir

    # Create coordinator and task agents with user's model/API key
    # Without these, CAMEL uses default models that lack credentials
    coordinator = ChatAgent(
        system_message="You coordinate task execution among specialized workers.",
        model=model,
    )
    task_agent = ChatAgent(
        system_message=(
            "You decompose complex tasks into smaller subtasks. "
            "Keep subtasks simple and practical. "
            "NEVER ask agents to extract raw HTML or full page source code. "
            "NEVER create overly detailed extraction schemas. "
            "Focus on high-level goals: browse, summarize, write, code."
        ),
        model=model,
    )

    workforce = CapeWorkforce(
        task_lock=task_lock,
        description="Cape Agent Workforce with browser, developer, and document agents",
        coordinator_agent=coordinator,
        task_agent=task_agent,
    )

    # Auto-connect browser if not already connected
    if not browser_service.connected:
        try:
            await browser_service.connect()
            logger.info("Browser service auto-connected for workforce")
        except Exception as e:
            logger.warning(f"Browser auto-connect failed: {e}")

    if browser_service.connected:
        browser_agent = create_browser_agent(task_lock, model, working_dir)
        workforce.add_single_agent_worker(
            description="Web research, browsing, and information gathering",
            worker=browser_agent,
        )

    developer_agent = create_developer_agent(task_lock, model, working_dir)
    workforce.add_single_agent_worker(
        description="Code writing, execution, and technical implementation",
        worker=developer_agent,
    )

    document_agent = create_document_agent(task_lock, model, working_dir)
    workforce.add_single_agent_worker(
        description="Document creation, file management, and content writing",
        worker=document_agent,
    )

    return workforce
