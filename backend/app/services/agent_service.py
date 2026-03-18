# backend/app/services/agent_service.py
import json
import logging
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
        model_config_dict={"stream": True, "temperature": 0.7},
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
    model = build_model(provider, model_name, api_key, api_base)

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
        async for partial in response:
            delta = partial.msg.content if partial.msg else ""
            if delta:
                full_content += delta
                yield {"type": "delta", "content": delta}
    else:
        if response.msgs:
            full_content = response.msgs[0].content
            yield {"type": "delta", "content": full_content}

    yield {"type": "done", "content": full_content}


def build_workforce(
    task_lock: TaskLock,
    provider: str,
    model_name: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
) -> CapeWorkforce:
    """Build a CapeWorkforce with browser, developer, and document agents."""
    model = build_model(provider, model_name, api_key, api_base)

    working_dir = tempfile.mkdtemp(prefix=f"cape_{task_lock.id[:8]}_")
    task_lock.working_directory = working_dir

    workforce = CapeWorkforce(
        task_lock=task_lock,
        description="Cape Agent Workforce with browser, developer, and document agents",
    )

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
