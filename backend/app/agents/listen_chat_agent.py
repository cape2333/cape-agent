import json
import logging
from typing import Any, Dict, Optional
from uuid import uuid4

from camel.agents import ChatAgent
from camel.agents._types import ToolCallRequest
from camel.toolkits import FunctionTool

from app.services.task_lock import TaskLock

logger = logging.getLogger(__name__)


class ListenChatAgent(ChatAgent):
    """ChatAgent that emits SSE events for agent activation and tool execution."""

    def __init__(self, task_lock: TaskLock, agent_name: str, **kwargs):
        super().__init__(**kwargs)
        self.task_lock = task_lock
        self.agent_name = agent_name
        self.agent_id = f"{agent_name.lower().replace(' ', '_')}_{uuid4().hex[:8]}"
        self.process_task_id: str = ""

    async def astep(self, input_message, **kwargs):
        await self.task_lock.put_event("activate_agent", {
            "agent_name": self.agent_name,
            "agent_id": self.agent_id,
            "process_task_id": self.process_task_id,
            "message": "",
        })

        try:
            response = await super().astep(input_message, **kwargs)

            final_message = ""
            if hasattr(response, "msg") and response.msg:
                final_message = response.msg.content or ""

            await self.task_lock.put_event("deactivate_agent", {
                "agent_name": self.agent_name,
                "agent_id": self.agent_id,
                "process_task_id": self.process_task_id,
                "message": final_message,
            })
            return response

        except Exception as e:
            await self.task_lock.put_event("deactivate_agent", {
                "agent_name": self.agent_name,
                "agent_id": self.agent_id,
                "process_task_id": self.process_task_id,
                "message": f"Error: {str(e)}",
            })
            raise

    async def _aexecute_tool(self, tool_call_request: ToolCallRequest):
        tool_name = tool_call_request.tool_name
        toolkit_name = self._resolve_toolkit_name(tool_name)
        tool_args = str(tool_call_request.args)[:200]

        await self.task_lock.put_event("activate_toolkit", {
            "agent_name": self.agent_name,
            "toolkit_name": toolkit_name,
            "method_name": tool_name,
            "message": tool_args,
        })

        try:
            result = await super()._aexecute_tool(tool_call_request)
            await self.task_lock.put_event("deactivate_toolkit", {
                "agent_name": self.agent_name,
                "toolkit_name": toolkit_name,
                "method_name": tool_name,
                "message": str(result)[:500],
            })
            return result
        except Exception as e:
            await self.task_lock.put_event("deactivate_toolkit", {
                "agent_name": self.agent_name,
                "toolkit_name": toolkit_name,
                "method_name": tool_name,
                "message": f"Error: {str(e)}",
            })
            raise

    async def _aexecute_tool_from_stream_data(
        self, tool_call_data: Dict[str, Any]
    ):
        tool_name = tool_call_data["function"]["name"]
        toolkit_name = self._resolve_toolkit_name(tool_name)
        tool_args = tool_call_data["function"].get("arguments", "")

        await self.task_lock.put_event("activate_toolkit", {
            "agent_name": self.agent_name,
            "toolkit_name": toolkit_name,
            "method_name": tool_name,
            "message": str(tool_args)[:200],
        })

        try:
            result = await super()._aexecute_tool_from_stream_data(tool_call_data)
            await self.task_lock.put_event("deactivate_toolkit", {
                "agent_name": self.agent_name,
                "toolkit_name": toolkit_name,
                "method_name": tool_name,
                "message": str(result)[:500],
            })
            return result
        except Exception as e:
            await self.task_lock.put_event("deactivate_toolkit", {
                "agent_name": self.agent_name,
                "toolkit_name": toolkit_name,
                "method_name": tool_name,
                "message": f"Error: {str(e)}",
            })
            raise

    def clone(self, with_memory: bool = False):
        """Clone preserving ListenChatAgent type and SSE event hooks."""
        cloned = super().clone(with_memory=with_memory)
        cloned.__class__ = ListenChatAgent
        cloned.task_lock = self.task_lock
        cloned.agent_name = self.agent_name
        cloned.agent_id = self.agent_id
        cloned.process_task_id = self.process_task_id
        return cloned

    def _resolve_toolkit_name(self, tool_name: str) -> str:
        return tool_name.split("_")[0] if "_" in tool_name else tool_name
