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

DEFAULT_SUMMARY_PROMPT = (
    "\n\nAfter completing the task, please generate a summary of the "
    "entire task completion. The summary must be enclosed in "
    "<summary></summary> tags and include:\n"
    "1. A confirmation of task completion, referencing the original goal.\n"
    "2. A high-level overview of the work performed and the final outcome.\n"
    "3. A bulleted list of key results or accomplishments.\n"
    "4. Any files created or important artifacts, with their full paths.\n"
    "Adopt a confident and professional tone."
)


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

    _ANALYZE_MAX_RETRIES = 3

    def _analyze_task(
        self,
        task: Task,
        *,
        for_failure: bool,
        error_message: str | None = None,
    ) -> TaskAnalysisResult:
        """Override quality evaluation with retry logic and fallback.

        Two improvements over CAMEL's default:

        1. **High-score acceptance**: CAMEL requires *both* ``score >= 70``
           **and** ``recovery_strategy is None``.  The evaluator LLM often
           suggests minor improvements even for excellent results (score 90+),
           triggering pointless retries.  When score >= QUALITY_ACCEPT_THRESHOLD
           we clear recovery fields so the result is accepted immediately.

        2. **Retry + fallback**: The evaluator LLM can return None or raise on
           transient failures.  We retry up to _ANALYZE_MAX_RETRIES times.
           If all retries fail on a normal task we accept the result with a
           score of 80 (the agent did its work; evaluation infrastructure broke).
           If all retries fail on an already-failed task we raise to halt.
        """
        last_exception: Exception | None = None

        for attempt in range(1, self._ANALYZE_MAX_RETRIES + 1):
            try:
                result = super()._analyze_task(
                    task, for_failure=for_failure, error_message=error_message,
                )

                if result is None:
                    logger.warning(
                        f"Task {task.id}: _analyze_task returned None "
                        f"(attempt {attempt}/{self._ANALYZE_MAX_RETRIES})"
                    )
                    continue

                # Accept high-quality results even when evaluator wants tweaks
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

            except Exception as e:
                last_exception = e
                logger.warning(
                    f"Task {task.id}: _analyze_task raised "
                    f"{type(e).__name__}: {e} "
                    f"(attempt {attempt}/{self._ANALYZE_MAX_RETRIES})"
                )

        # All retries exhausted
        logger.error(
            f"Task {task.id}: _analyze_task failed after "
            f"{self._ANALYZE_MAX_RETRIES} retries, for_failure={for_failure}"
        )

        if for_failure:
            # Task already failed + evaluation failed — halt
            raise RuntimeError(
                f"_analyze_task failed after {self._ANALYZE_MAX_RETRIES} "
                f"retries for already-failed task {task.id}"
            ) from last_exception

        # Normal task: accept the result with a passing score so the agent's
        # actual work (which completed successfully) is not discarded.
        return TaskAnalysisResult(
            reasoning=(
                f"_analyze_task failed after {self._ANALYZE_MAX_RETRIES} "
                f"retries — accepting task result as-is"
            ),
            quality_score=80,
        )

    def _sync_subtask_to_parent(self, task: Task) -> None:
        """Sync completed subtask result/state back to parent.subtasks.

        CAMEL stores finished tasks in ``_completed_tasks`` but does not
        write the result back to ``parent.subtasks[i]``.  This causes
        ``parent.subtasks[i].result`` to remain ``None`` when the
        coordinator or evaluator inspects the parent task tree.
        """
        parent = task.parent
        if not parent or not parent.subtasks:
            return

        for sub in parent.subtasks:
            if sub.id == task.id:
                sub.result = task.result
                sub.state = task.state
                logger.debug(
                    f"[SYNC] Synced subtask {task.id} result to parent.subtasks"
                )
                return

        logger.warning(f"[SYNC] Subtask {task.id} not found in parent.subtasks")

    async def _handle_completed_task(self, task: Task) -> None:
        """Sync subtask result to parent before delegating to CAMEL."""
        self._sync_subtask_to_parent(task)
        await super()._handle_completed_task(task)

    async def run(self, question: str):
        task_content = question + DEFAULT_SUMMARY_PROMPT
        main_task = Task(content=task_content, id=f"main_{uuid4().hex[:8]}")
        self.task_lock.status = Status.decomposing

        # Inject conversation history so the decomposer knows what
        # previous rounds accomplished (files created, results, etc.)
        # Lazy import to avoid circular dependency: agent_service imports
        # CapeWorkforce, so a top-level import here would fail.
        from app.services.agent_service import build_conversation_context

        context = build_conversation_context(self.task_lock)
        if context:
            original_content = main_task.content
            main_task.content = (
                context
                + "\n\n=== CURRENT TASK ===\n"
                + original_content
            )

        try:
            self.task_lock.status = Status.executing
            result = await self.process_task_async(main_task)

            # Restore original content to avoid polluting the task tree
            if context:
                main_task.content = original_content

            return result
        except Exception as e:
            await self.task_lock.put_event("error", {
                "message": f"Workforce error: {str(e)}"
            })
            raise
