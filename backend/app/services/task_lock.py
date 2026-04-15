import asyncio
from dataclasses import dataclass, field
from typing import Optional

from app.models.enums import Status


@dataclass
class TaskLock:
    id: str
    status: Status
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    workforce: Optional[object] = None
    working_directory: str = ""
    background_tasks: set = field(default_factory=set)
    conversation_history: list = field(default_factory=list)
    human_input: dict = field(default_factory=dict)

    def add_human_input_listener(self, agent_name: str):
        """Register a per-agent asyncio.Queue for human replies."""
        self.human_input[agent_name] = asyncio.Queue(maxsize=1)

    async def get_human_input(self, agent_name: str) -> str:
        """Block until the user replies to this agent's question."""
        return await self.human_input[agent_name].get()

    async def put_human_input(self, agent_name: str, response: str):
        """Deliver the user's reply to the waiting agent."""
        await self.human_input[agent_name].put(response)

    async def put_event(self, step: str, data: dict):
        await self.queue.put({"step": step, "data": data})

    def emit_sync(self, step: str, data: dict) -> bool:
        """Best-effort synchronous event emission.

        Returns True if enqueued. Never raises — callers that run outside
        an async context (e.g. agent tool calls) use this to surface
        progress without having to juggle event loops.
        """
        try:
            self.queue.put_nowait({"step": step, "data": data})
            return True
        except Exception:
            return False

    async def get_event(self) -> dict:
        return await self.queue.get()

    async def cleanup(self):
        if self.workforce and hasattr(self.workforce, "stop"):
            self.workforce.stop()
        for task in self.background_tasks:
            task.cancel()
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        for q in self.human_input.values():
            while not q.empty():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    break
        self.human_input.clear()
