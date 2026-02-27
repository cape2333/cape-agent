from typing import AsyncGenerator, List, Optional
from camel.agents import ChatAgent
from camel.messages import BaseMessage
from camel.models import ModelFactory
from camel.types import ModelPlatformType, OpenAIBackendRole, RoleType


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
) -> ChatAgent:
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

    agent = ChatAgent(
        system_message="You are a helpful AI assistant.",
        model=model,
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


async def stream_chat(
    agent: ChatAgent,
    user_message: str,
) -> AsyncGenerator[str, None]:
    response = await agent.astep(user_message)

    async for partial in response:
        delta = partial.msg.content if partial.msg else ""
        if delta:
            yield delta
