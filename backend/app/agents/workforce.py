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
from camel.societies.workforce.utils import TaskAnalysisResult
from camel.tasks import Task

from app.models.enums import Status
from app.services.task_lock import TaskLock

logger = logging.getLogger(__name__)


class CapeWorkforceCallback(WorkforceCallback):
    """Translates CAMEL Workforce lifecycle events into SSE events."""

    def __init__(self, task_lock: TaskLock):
        self.task_lock = task_lock
        self._loop = asyncio.get_event_loop()
        self._subtask_results: dict[str, dict] = {}  # task_id -> {content, result}

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
        result_text = event.result_summary or ""
        # Only accumulate leaf subtask results (IDs contain '.')
        # Skip the parent/main task which has aggregated results
        if "." in event.task_id:
            self._subtask_results[event.task_id] = {
                "result": result_text,
            }
        self._emit("task_state", {
            "task_id": event.task_id,
            "state": "done",
            "result": result_text,
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
        self._emit("end", {
            "content": "All tasks completed.",
            "subtask_results": self._subtask_results,
        })


class CapeWorkforce(Workforce):
    """Workforce with SSE event streaming via callback."""

    # Quality score threshold: results scoring at or above this value are
    # accepted regardless of whether the evaluator suggests a recovery
    # strategy.  CAMEL's default logic rejects any result that has a
    # recovery_strategy, even with score 90+, causing unnecessary retries.
    QUALITY_ACCEPT_THRESHOLD = 85

    def __init__(self, task_lock: TaskLock, **kwargs):
        callback = CapeWorkforceCallback(task_lock)
        super().__init__(callbacks=[callback], **kwargs)
        self.task_lock = task_lock

    def _analyze_task(
        self,
        task: Task,
        *,
        for_failure: bool,
        error_message: str | None = None,
    ) -> TaskAnalysisResult:
        """Override quality evaluation to accept high-score results.

        CAMEL's default ``quality_sufficient`` requires *both*
        ``score >= 70`` **and** ``recovery_strategy is None``.  The
        evaluator LLM often suggests minor improvements even for
        excellent results (score 90+), which triggers pointless retries
        that then fail due to context-length overflow.

        When the score meets ``QUALITY_ACCEPT_THRESHOLD`` we clear the
        recovery fields so the result is accepted on the first pass.
        """
        result = super()._analyze_task(
            task, for_failure=for_failure, error_message=error_message,
        )
        if (
            not for_failure
            and result.quality_score is not None
            and result.quality_score >= self.QUALITY_ACCEPT_THRESHOLD
            and not result.quality_sufficient
        ):
            logger.info(
                f"Task {task.id}: accepting result with score "
                f"{result.quality_score} (>= {self.QUALITY_ACCEPT_THRESHOLD})"
            )
            result.recovery_strategy = None
            result.issues = []
        return result

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
