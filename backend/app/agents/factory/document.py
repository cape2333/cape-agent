from camel.messages import BaseMessage
from camel.toolkits import FileToolkit, NoteTakingToolkit

from app.agents.listen_chat_agent import ListenChatAgent
from app.services.task_lock import TaskLock

DOCUMENT_SYSTEM_PROMPT = """\
You are a Documentation Specialist. Your role is to create, modify, and \
manage documents in various formats.

Use write_to_file to create documents (Markdown, HTML, CSV, JSON, YAML). \
Use read_file to read existing documents. Use edit_file to modify them.

Before creating documents, use list_note and read_note to gather \
information from other agents. After creating documents, register them \
with append_note("shared_files", "- path: description").

Always use tools to create documents — never just output text as your response.
"""


def create_document_agent(
    task_lock: TaskLock, model, working_directory: str
) -> ListenChatAgent:
    file_toolkit = FileToolkit(
        working_directory=working_directory,
        default_encoding="utf-8",
        backup_enabled=True,
    )
    note_toolkit = NoteTakingToolkit(working_directory=working_directory)
    tools = file_toolkit.get_tools() + note_toolkit.get_tools()

    return ListenChatAgent(
        task_lock=task_lock,
        agent_name="Document Agent",
        system_message=BaseMessage.make_assistant_message(
            role_name="Document Agent",
            content=DOCUMENT_SYSTEM_PROMPT,
        ),
        tools=tools,
        model=model,
    )
