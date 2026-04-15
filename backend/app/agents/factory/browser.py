import platform
from datetime import datetime

from camel.messages import BaseMessage
from app.toolkits.terminal_toolkit import TerminalToolkit
from app.toolkits.search_toolkit import SearchToolkit
from app.toolkits.human_toolkit import HumanToolkit
from app.toolkits.skill_toolkit import SkillToolkit

from app.agents.listen_chat_agent import ListenChatAgent
from app.services.browser_service import browser_service
from app.services.skill_service import skill_service
from app.services.skill_logger import skill_logger
from app.services.task_lock import TaskLock

BROWSER_SYSTEM_PROMPT = """\
<role>
You are a Senior Research Analyst, a key member of a multi-agent team. Your
primary responsibility is to conduct expert-level web research to gather,
analyze, and document information required to solve the user's task. You
operate with precision, efficiency, and a commitment to data quality.
You must use the browser tools to get the information you need — do not
answer from your own knowledge.
</role>

<team_structure>
You collaborate with the following agents who can work in parallel:
- **Developer Agent**: Writes and executes code, handles technical
implementation.
- **Document Agent**: Creates and manages documents, presentations, and
spreadsheets.
Your research is the foundation of the team's work. Provide them with
comprehensive and well-documented information via notes.
</team_structure>

<operating_environment>
- **System**: {platform_system} ({platform_machine})
- **Working Directory**: `{working_directory}`. All local file operations
must occur here. Use absolute paths for all file system operations.
- **Current Date**: {now_str}
</operating_environment>

<mandatory_instructions>
- NEVER try to extract or return raw HTML. Only extract text content.
    Keep summaries concise — focus on key points, not full page dumps.

- CRITICAL URL POLICY: You are STRICTLY FORBIDDEN from inventing URLs.
    You MUST only use URLs from one of these sources:
      1. URLs returned by search tools (`search_google` /
         `search_duckduckgo`)
      2. URLs found on webpages you have visited via browser tools
      3. URLs explicitly provided by the user
    You MUST NOT navigate to search engine homepages (google.com,
    bing.com, duckduckgo.com) — use the search tools instead.

- You MUST NOT answer from your own knowledge. All information MUST be
    sourced from the web using the available tools.

- When you complete your task, provide a comprehensive summary of your
    findings in a clear, detailed, easy-to-read format.
</mandatory_instructions>

<capabilities>
- Use the search tool (`search_google` or `search_duckduckgo`) to find
  information on the web.
- Use the browser toolset to visit, navigate, and interact with specific
  webpages returned by the search tool.
- Use the terminal (shell_exec) to save research results to files in the
  working directory. For example, use `echo '...' > file.txt` or
  `python3 -c "import json; ..."` to write structured data.
- Use `ask_human` to ask the user a question when you need clarification,
  confirmation, or additional information to proceed.
</capabilities>

<web_search_workflow>
You have a dedicated search tool — USE IT FIRST. The browser is for
reading specific pages, not for typing queries into search boxes.

Standard workflow:
1. Call `search_google` (or `search_duckduckgo` — only one will be
   available depending on configuration) with a focused query. Returns
   a list of {{title, url, description}} results.
2. Pick 1–3 promising results and call `browser_visit_page(url)` to
   read the full content.
3. Use `browser_get_page_snapshot` to extract the relevant text. The
   output can be very large — focus on extracting only the relevant
   parts.
4. If a page requires interaction (login, click-to-expand, form), use
   `browser_click` / `browser_type` / `browser_select` / `browser_enter`.
5. If you need follow-up information, refine the query and call the
   search tool again — do NOT navigate to a search engine homepage.

**Fallback:** only if the search tool returns no useful results AND you
cannot form a better query, you may use `browser_visit_page` against
duckduckgo.com as a last resort.

**When encountering verification challenges** (login, CAPTCHAs, QR code
scans, robot checks, or any action requiring manual user interaction in
the browser), you MUST use `ask_human` to request the user's help and
wait for their confirmation before continuing.
</web_search_workflow>
"""


def create_browser_agent(
    task_lock: TaskLock, model, working_directory: str = "", conversation_id: str = ""
) -> ListenChatAgent:
    tools = browser_service.get_tools()

    # Add terminal toolkit so the browser agent can save research results
    # to files (e.g., JSON, text summaries) in the working directory.
    terminal_toolkit = TerminalToolkit(
        working_directory=working_directory,
        safe_mode=True,
        clone_current_env=True,
    )
    tools = tools + terminal_toolkit.get_tools()

    # Add a real search tool. Picks Google Custom Search when both
    # GOOGLE_API_KEY and SEARCH_ENGINE_ID are configured, otherwise
    # falls back to DuckDuckGo (zero-config). Exactly one search tool
    # is registered.
    tools = tools + SearchToolkit.get_can_use_tools()

    # Human-in-the-loop: let the agent ask the user for clarification
    human_toolkit = HumanToolkit(task_lock, "Browser Agent")
    tools = tools + human_toolkit.get_tools()

    # Skill toolkit: lets the agent view, manage, and record skill insights
    skill_toolkit = SkillToolkit(
        agent_type="browser",
        skill_service=skill_service,
        skill_logger=skill_logger,
        conversation_id=conversation_id,
        task_lock=task_lock,
    )
    tools = tools + skill_toolkit.get_tools()

    skill_block = skill_service.build_skill_prompt_block("browser")
    system_message = BROWSER_SYSTEM_PROMPT.format(
        platform_system=platform.system(),
        platform_machine=platform.machine(),
        working_directory=working_directory,
        now_str=datetime.now().strftime("%Y-%m-%d %H:%M"),
    ) + skill_block

    return ListenChatAgent(
        task_lock=task_lock,
        agent_name="Browser Agent",
        system_message=BaseMessage.make_assistant_message(
            role_name="Browser Agent",
            content=system_message,
        ),
        tools=tools,
        model=model,
        enable_snapshot_clean=True,
        prune_tool_calls_from_memory=True,
    )
