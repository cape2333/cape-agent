from camel.messages import BaseMessage
from camel.toolkits import NoteTakingToolkit
from camel.toolkits.terminal_toolkit import TerminalToolkit

from app.agents.listen_chat_agent import ListenChatAgent
from app.services.task_lock import TaskLock

DEVELOPER_SYSTEM_PROMPT = """\
You are a Lead Software Engineer. Your role is to solve technical tasks \
by writing and executing code, installing libraries, and interacting \
with the operating system.

You have full terminal access. Use shell_exec to run commands.

After creating files or producing results, use note-taking tools to \
register your work so other agents can access it.

Principles:
- Bias for action: execute code, don't just suggest it
- Verify your work by running and testing
- Keep the user informed with brief progress updates
"""


def create_developer_agent(
    task_lock: TaskLock, model, working_directory: str
) -> ListenChatAgent:
    terminal_toolkit = TerminalToolkit(
        working_directory=working_directory,
        safe_mode=True,
        clone_current_env=True,
        timeout=30.0,
    )
    note_toolkit = NoteTakingToolkit(working_directory=working_directory)
    tools = terminal_toolkit.get_tools() + note_toolkit.get_tools()

    return ListenChatAgent(
        task_lock=task_lock,
        agent_name="Developer Agent",
        system_message=BaseMessage.make_assistant_message(
            role_name="Developer Agent",
            content=DEVELOPER_SYSTEM_PROMPT,
        ),
        tools=tools,
        model=model,
    )
