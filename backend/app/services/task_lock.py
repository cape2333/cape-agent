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

    async def put_event(self, step: str, data: dict):
        await self.queue.put({"step": step, "data": data})

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
