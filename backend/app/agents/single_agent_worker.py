import logging
from typing import List

from camel.societies.workforce import SingleAgentWorker
from camel.tasks import Task, TaskState

from app.agents.listen_chat_agent import ListenChatAgent

logger = logging.getLogger(__name__)

PROCESS_TASK_PROMPT = """You are assigned the following task:

**Task:** {content}

**Parent Task Context:** {parent_task_content}

**Dependency Results:**
{dependency_tasks_info}

Complete this task thoroughly. When done, provide your result as a clear,
actionable summary of what was accomplished."""


class CapeAgentWorker(SingleAgentWorker):
    """Worker that sets process_task_id for SSE event correlation."""

    def __init__(self, description: str, worker: ListenChatAgent, **kwargs):
        super().__init__(description=description, worker=worker, **kwargs)
        self._cape_worker = worker

    async def _process_task(
        self, task: Task, dependencies: List[Task]
    ) -> TaskState:
        self._cape_worker.process_task_id = task.id

        dep_info = self._format_dependencies(dependencies)
        parent_content = task.parent.content if task.parent else "N/A"

        prompt = PROCESS_TASK_PROMPT.format(
            content=task.content,
            parent_task_content=parent_content,
            dependency_tasks_info=dep_info if dep_info else "None",
        )

        try:
            response = await self._cape_worker.astep(prompt)

            response_content = ""
            if hasattr(response, "msg") and response.msg:
                response_content = response.msg.content or ""

            task.result = response_content
            return TaskState.DONE

        except Exception as e:
            logger.error(f"Task {task.id} failed: {e}", exc_info=True)
            task.result = f"Failed: {str(e)}"
            return TaskState.FAILED

    def _format_dependencies(self, dependencies: List[Task]) -> str:
        if not dependencies:
            return ""
        lines = []
        for dep in dependencies:
            result = dep.result if dep.result else "No result"
            lines.append(f"- [{dep.id}] {dep.content}: {result}")
        return "\n".join(lines)
