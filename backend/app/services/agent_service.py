# backend/app/services/agent_service.py
import logging
import os
import platform
import re
from datetime import datetime
from pathlib import Path
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

COORDINATOR_PROMPT_TEMPLATE = """\
You are the Coordinator of a multi-agent workforce. Your role is to oversee \
task execution and ensure all subtasks are completed successfully.

<operating_environment>
- **System**: {platform_system} ({platform_machine})
- **Working Directory**: `{working_directory}`. All agents share this \
directory for file operations. Any file paths in subtasks MUST use this \
directory as the base path. Do NOT invent paths like /workspace, /output, \
or /tmp — always use the working directory above.
- **Current Date**: {now_str}
</operating_environment>

<available_workers>
You have the following specialized agents at your disposal:
- **Browser Agent (Senior Research Analyst)**: Web research, browsing, \
information gathering from the internet. Use for any task requiring online \
data, fact-checking, or web navigation.
- **Developer Agent (Lead Software Engineer)**: Code writing, execution, \
terminal commands, package installation, and technical implementation. Use \
for any task requiring programming or system interaction.
- **Document Agent (Documentation Specialist)**: Document creation and \
management — Word, PDF, HTML, Markdown, PowerPoint, Excel. Use for any \
task requiring file output or structured content.
</available_workers>

<coordination_strategy>
- Assign each subtask to the most appropriate worker based on its nature.
- When subtasks have dependencies, ensure prerequisite tasks complete first.
- If a worker's result is insufficient, provide clear feedback on what \
needs improvement before requesting a retry.
- Monitor overall progress and ensure the final output addresses the \
user's original request completely.
- Prefer parallel execution when subtasks are independent.
- When a subtask requires file output, specify the exact file path using \
the working directory (e.g., `{working_directory}/output.py`).
</coordination_strategy>
"""

TASK_DECOMPOSER_PROMPT_TEMPLATE = """\
You decompose complex tasks into smaller, actionable subtasks for a \
multi-agent workforce.

<operating_environment>
- **System**: {platform_system} ({platform_machine})
- **Working Directory**: `{working_directory}`. All file output MUST be \
saved to this directory. Use absolute paths based on this directory in \
subtask descriptions. Do NOT use generic paths like /workspace, /output, \
or /tmp — always use the working directory above.
- **Current Date**: {now_str}
</operating_environment>

<available_workers>
The workforce has these specialized agents:
- **Browser Agent**: Web research and information gathering from the internet.
- **Developer Agent**: Code writing, execution, and technical implementation.
- **Document Agent**: Document creation (Word, PDF, HTML, PowerPoint, Excel).
</available_workers>

<decomposition_principles>
- **Self-contained subtasks**: Each subtask MUST be fully independent and \
understandable in isolation. Do NOT use relative references like "based on \
the previous step", "from the first task", or "using the above results". \
If a subtask needs upstream output, explicitly describe the required \
content (e.g., "Analyze the document titled 'React Framework Comparison' \
saved at {working_directory}/comparison.md").
- **Strategic grouping**: Sequential actions that require the same worker \
type SHOULD be grouped into a single subtask to reduce scheduling \
overhead. For example, "search for React info" + "search for Vue info" \
should be one Browser Agent subtask, not two.
- **Aggressive parallelization**: Different worker specializations MUST be \
split into separate subtasks to enable parallel execution. Multiple \
independent items of the same type SHOULD also be split into parallel \
subtasks when they don't share state.
- **Balanced granularity**: Each subtask should be large enough to be \
meaningful and small enough for effective parallelism. Avoid \
over-decomposition — splitting into too many tiny tasks adds overhead \
without benefit.
- Match subtasks to agent capabilities: research tasks for Browser Agent, \
coding tasks for Developer Agent, document tasks for Document Agent.
- Identify dependencies between subtasks and order them logically. \
Independent subtasks should be marked for parallel execution.
- NEVER ask agents to extract raw HTML or full page source code.
- NEVER create overly detailed extraction schemas.
- Focus on high-level goals: browse, summarize, write, code.
- Each subtask description should be self-contained with enough context \
for the assigned agent to work independently.
- When a subtask requires file output, specify the exact file path using \
the working directory (e.g., `{working_directory}/output.py`).
</decomposition_principles>
"""

SUMMARY_AGENT_PROMPT = """\
You are the Final Summarizer of a multi-agent workforce system. Your job \
is to synthesize results from multiple specialized agents (Browser Agent, \
Developer Agent, Document Agent) into a single, coherent response for the \
user.

<input_format>
Each subtask result may contain a <summary></summary> block produced by \
the agent. Prioritize content within these tags as the authoritative \
outcome of that subtask. If no <summary> tag is present, use the full \
result text.
</input_format>

<output_guidelines>
- Lead with the answer or main outcome — do not repeat the user's question.
- Organize by logical topic, NOT by subtask number. Merge related findings \
from different subtasks into unified sections.
- Preserve concrete artifacts: file paths, URLs, code snippets, data \
tables, and key statistics.
- Use markdown formatting (headings, bullet points, code blocks) for \
readability.
- Keep the summary concise but complete — omit intermediate steps and \
tool-call details, retain conclusions and deliverables.
- If a subtask failed or produced no result, mention it briefly without \
dwelling on it.
</output_guidelines>
"""


def _extract_summary(text: str) -> str:
    """Extract content from <summary> tags, falling back to truncation."""
    match = re.search(r"<summary>(.*?)</summary>", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: truncate
    if len(text) > 3000:
        return text[:3000] + "\n... (truncated)"
    return text


def build_conversation_context(task_lock: TaskLock) -> str:
    """Build structured context from previous workforce rounds.

    Returns a formatted string summarizing all previous rounds'
    task content, results, and generated files. Returns empty string
    if no conversation history exists.
    """
    if not task_lock.conversation_history:
        return ""

    parts = ["=== CONVERSATION HISTORY ==="]
    for i, entry in enumerate(task_lock.conversation_history, 1):
        parts.append(f"\n**Round {i}**")
        parts.append(f"Task: {entry['task_content']}")
        result = entry.get("task_result", "")
        if result:
            parts.append(f"Result: {result}")

    # Collect all generated files across rounds
    all_dirs = [
        e["working_directory"]
        for e in task_lock.conversation_history
        if e.get("working_directory")
    ]
    if all_dirs:
        files = []
        for d in all_dirs:
            dir_path = Path(d)
            if dir_path.exists():
                files.extend(
                    str(f) for f in dir_path.rglob("*") if f.is_file()
                )
        if files:
            parts.append(f"\nGenerated Files: {files}")

    return "\n".join(parts)


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
    extra_config: Optional[dict] = None,
):
    """Create a CAMEL model backend."""
    plat = PLATFORM_MAP.get(provider, ModelPlatformType.OPENAI)
    kwargs = {}
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["url"] = api_base

    config = {"stream": stream, "temperature": 0.7}
    if extra_config:
        config.update(extra_config)

    return ModelFactory.create(
        model_platform=plat,
        model_type=model_name,
        model_config_dict=config,
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

    # Single subtask: extract summary and return directly
    if len(results) == 1:
        raw = results[0].get("result", "") or "Task completed."
        return _extract_summary(raw)

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
            system_message=SUMMARY_AGENT_PROMPT,
            model=summary_model,
        )

        subtasks_info = ""
        for i, (task_id, info) in enumerate(subtask_results.items(), 1):
            result_text = info.get("result", "") or "No result"
            # Smart extraction: prefer <summary> tags, fallback to truncation
            result_text = _extract_summary(result_text)
            subtasks_info += f"\n**Subtask {i}** ({task_id})\n"
            subtasks_info += f"Result: {result_text}\n"
            subtasks_info += "---\n"

        prompt = (
            f"Synthesize the following subtask results into a unified "
            f"response for the user.\n\n"
            f"User's original request: {original_question}\n\n"
            f"Subtask results:\n{subtasks_info}"
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

    working_dir = str(
        Path.home() / ".cape-agent" / "workspace" / task_lock.id
    )
    os.makedirs(working_dir, exist_ok=True)
    task_lock.working_directory = working_dir

    # Format prompts with environment info so coordinator and task
    # decomposer use the correct working directory instead of inventing
    # paths like /workspace that may not exist on the host OS.
    env_vars = dict(
        working_directory=working_dir,
        platform_system=platform.system(),
        platform_machine=platform.machine(),
        now_str=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    # Create coordinator and task agents with user's model/API key
    # Without these, CAMEL uses default models that lack credentials
    coordinator = ChatAgent(
        system_message=COORDINATOR_PROMPT_TEMPLATE.format(**env_vars),
        model=model,
    )
    task_agent = ChatAgent(
        system_message=TASK_DECOMPOSER_PROMPT_TEMPLATE.format(**env_vars),
        model=model,
    )

    # Template agent for workers created dynamically at runtime (e.g. when
    # CAMEL's failure-handling strategy creates a new specialised worker).
    # Without this, CAMEL falls back to its default model which lacks the
    # user's API key / base URL, causing 401 errors.
    new_worker_agent = ChatAgent(
        system_message=(
            f"You are a helpful assistant.\n"
            f"- System: {env_vars['platform_system']} "
            f"({env_vars['platform_machine']})\n"
            f"- Working directory: `{working_dir}`. Use absolute paths.\n"
            f"- Current date: {env_vars['now_str']}\n"
        ),
        model=model,
    )

    workforce = CapeWorkforce(
        task_lock=task_lock,
        description="Cape Agent Workforce with browser, developer, and document agents",
        coordinator_agent=coordinator,
        task_agent=task_agent,
        new_worker_agent=new_worker_agent,
    )

    # Auto-connect browser if not already connected
    if not browser_service.connected:
        try:
            await browser_service.connect()
            logger.info("Browser service auto-connected for workforce")
        except Exception as e:
            logger.warning(f"Browser auto-connect failed: {e}")

    if browser_service.connected:
        # Disable parallel tool calls to prevent concurrent browser actions
        # that corrupt page state. CAMEL 0.2.90a6+ strips this param from
        # requests with no tools, so _context_summary_agent won't 400.
        browser_model = build_model(
            provider, model_name, api_key, api_base, stream=False,
            extra_config={"parallel_tool_calls": False},
        )
        browser_agent = create_browser_agent(task_lock, browser_model, working_dir)
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
