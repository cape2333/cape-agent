"""Toolkit that lets agents ask the user a question via the GUI."""

from camel.toolkits import FunctionTool

from app.services.task_lock import TaskLock


class HumanToolkit:
    """Provides a single tool for agents to ask the human user a question.

    When ``ask_human`` is called the toolkit:
    1. Emits an ``"ask"`` SSE event so the frontend can display the question.
    2. Blocks (``await``) until the user submits a reply via the REST endpoint.
    3. Returns the user's reply as a plain string to the calling agent.
    """

    def __init__(self, task_lock: TaskLock, agent_name: str) -> None:
        self.task_lock = task_lock
        self.agent_name = agent_name
        task_lock.add_human_input_listener(agent_name)

    async def ask_human(self, question: str) -> str:
        """Ask the human user a question and wait for their response.

        Use this tool when you are stuck, need clarification, require a
        decision to be made, or need additional information from the user
        to proceed with your task. Examples:
        - Clarify ambiguous instructions or requirements.
        - Request missing information (e.g., login credentials, file paths).
        - Ask for a decision when there are multiple viable options.
        - Seek help when you encounter an error you cannot resolve on your own.

        Args:
            question (str): The question to ask the user.

        Returns:
            str: The user's response.
        """
        await self.task_lock.put_event("ask", {
            "agent_name": self.agent_name,
            "question": question,
        })
        return await self.task_lock.get_human_input(self.agent_name)

    def get_tools(self) -> list[FunctionTool]:
        return [FunctionTool(self.ask_human)]
