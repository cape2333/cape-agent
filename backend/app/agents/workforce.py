import asyncio
import logging
from uuid import uuid4

from camel.societies.workforce import Workforce
from camel.societies.workforce.workforce_callback import WorkforceCallback
from camel.societies.workforce.events import (
    TaskCreatedEvent,
    TaskDecomposedEvent,
    TaskAssignedEvent,
    TaskStartedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    AllTasksCompletedEvent,
    WorkerCreatedEvent,
    WorkerDeletedEvent,
)
from camel.tasks import Task

from app.models.enums import Status
from app.services.task_lock import TaskLock

logger = logging.getLogger(__name__)


class CapeWorkforceCallback(WorkforceCallback):
    """Translates CAMEL Workforce lifecycle events into SSE events."""

    def __init__(self, task_lock: TaskLock):
        self.task_lock = task_lock
        self._loop = asyncio.get_event_loop()

    def _emit(self, step: str, data: dict):
        asyncio.run_coroutine_threadsafe(
            self.task_lock.put_event(step, data),
            self._loop,
        )

    def log_task_created(self, event: TaskCreatedEvent) -> None:
        pass

    def log_task_decomposed(self, event: TaskDecomposedEvent) -> None:
        self._emit("decompose_progress", {
            "sub_tasks": [
                {"id": tid, "content": tid, "state": "open"}
                for tid in event.subtask_ids
            ],
            "is_final": True,
        })

    def log_task_assigned(self, event: TaskAssignedEvent) -> None:
        self._emit("assign_task", {
            "task_id": event.task_id,
            "assignee_id": event.worker_id,
            "content": "",
            "state": "waiting",
        })

    def log_task_started(self, event: TaskStartedEvent) -> None:
        self._emit("assign_task", {
            "task_id": event.task_id,
            "assignee_id": event.worker_id,
            "content": "",
            "state": "running",
        })

    def log_task_completed(self, event: TaskCompletedEvent) -> None:
        self._emit("task_state", {
            "task_id": event.task_id,
            "state": "done",
            "result": event.result_summary or "",
            "content": "",
        })

    def log_task_failed(self, event: TaskFailedEvent) -> None:
        self._emit("task_state", {
            "task_id": event.task_id,
            "state": "failed",
            "result": event.error_message,
            "content": "",
        })

    def log_worker_created(self, event: WorkerCreatedEvent) -> None:
        pass

    def log_worker_deleted(self, event: WorkerDeletedEvent) -> None:
        pass

    def log_all_tasks_completed(self, event: AllTasksCompletedEvent) -> None:
        self._emit("end", {"content": "All tasks completed."})


class CapeWorkforce(Workforce):
    """Workforce with SSE event streaming via callback."""

    def __init__(self, task_lock: TaskLock, **kwargs):
        callback = CapeWorkforceCallback(task_lock)
        super().__init__(callbacks=[callback], **kwargs)
        self.task_lock = task_lock

    async def run(self, question: str):
        main_task = Task(content=question, id=f"main_{uuid4().hex[:8]}")
        self.task_lock.status = Status.decomposing

        try:
            self.task_lock.status = Status.executing
            result = await self.process_task_async(main_task)
            return result
        except Exception as e:
            await self.task_lock.put_event("error", {
                "message": f"Workforce error: {str(e)}"
            })
            raise
