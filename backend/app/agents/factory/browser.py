from camel.messages import BaseMessage
from camel.toolkits import NoteTakingToolkit

from app.agents.listen_chat_agent import ListenChatAgent
from app.services.browser_service import browser_service
from app.services.task_lock import TaskLock

BROWSER_SYSTEM_PROMPT = """\
You are a Senior Research Analyst. Your primary role is to conduct web \
research to gather, analyze, and document information.

You must use search/browser tools to get information — do not answer from \
your own knowledge.

After finding information, use note-taking tools to record your findings \
so other agents can access them.

IMPORTANT RULES:
- NEVER try to extract or return raw HTML. Only extract text content.
- Keep your summaries concise. Focus on key points, not full page dumps.
- When using browser_get_page_snapshot, the output can be very large. \
Focus on extracting only the relevant parts you need.

Workflow:
1. Use browser_visit_page to navigate to relevant websites
2. Use browser_get_page_snapshot to understand page content
3. Interact with elements using browser_click, browser_type, browser_select
4. Record key findings with create_note or append_note (concise text only)
5. Provide a comprehensive but concise summary when done
"""


def create_browser_agent(
    task_lock: TaskLock, model, working_directory: str = ""
) -> ListenChatAgent:
    browser_tools = browser_service.get_tools()
    note_toolkit = NoteTakingToolkit(working_directory=working_directory)
    tools = browser_tools + note_toolkit.get_tools()

    return ListenChatAgent(
        task_lock=task_lock,
        agent_name="Browser Agent",
        system_message=BaseMessage.make_assistant_message(
            role_name="Browser Agent",
            content=BROWSER_SYSTEM_PROMPT,
        ),
        tools=tools,
        model=model,
        enable_snapshot_clean=True,
        prune_tool_calls_from_memory=True,
    )
