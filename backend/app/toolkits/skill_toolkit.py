"""Toolkit that gives workforce agents skill_view, skill_manage, and mark_insight tools."""

from __future__ import annotations

import logging
from typing import Optional

from camel.toolkits import FunctionTool

from app.services.skill_service import SkillService
from app.services.skill_logger import SkillLogger

logger = logging.getLogger(__name__)


class SkillToolkit:
    def __init__(
        self,
        agent_type: str,
        skill_service: SkillService,
        skill_logger: SkillLogger,
        conversation_id: str = "",
        task_lock=None,
    ):
        self.agent_type = agent_type
        self._svc = skill_service
        self._logger = skill_logger
        self._conversation_id = conversation_id
        self._task_lock = task_lock

    def _emit_event(self, step: str, data: dict) -> None:
        """Best-effort SSE event emission. Safe to call from sync code and
        from contexts without a running event loop.
        """
        if not self._task_lock:
            return
        if not self._task_lock.emit_sync(step, data):
            logger.warning("skill event %s dropped (queue unavailable)", step)

    def skill_view(self, name: str, file_path: Optional[str] = None) -> str:
        """Load a skill's full content by name.

        Use this to read the detailed instructions of a skill listed in
        your Available Skills section. Returns the skill's markdown body.

        Args:
            name: The skill name to view.
            file_path: Optional path to a supporting file (e.g. "references/api.md").

        Returns:
            The skill content as markdown, or an error message.
        """
        detail = self._svc.get_skill(name)
        if not detail:
            return f"Skill '{name}' not found. Use the skills listed in your Available Skills section."

        self._logger.log_event(
            "skill_loaded", name, detail.agent_type, self._conversation_id
        )

        self._emit_event("skill_loaded", {"skill": name, "agent": self.agent_type})

        if file_path:
            target = self._svc.resolve_skill_file(name, file_path)
            if target is None:
                return f"Invalid file path '{file_path}' for skill '{name}'."
            if target.is_file():
                return target.read_text(encoding="utf-8")
            return f"File '{file_path}' not found in skill '{name}'. Available: {detail.files}"

        return detail.content

    def skill_manage(
        self,
        action: str,
        name: str,
        content: Optional[str] = None,
        old_string: Optional[str] = None,
        new_string: Optional[str] = None,
    ) -> str:
        """Create, update, or delete a skill.

        Use this after completing a difficult task to save your approach,
        or when you find an existing skill needs correction.

        Args:
            action: One of "create", "patch", "edit", "delete".
            name: The skill name.
            content: Full SKILL.md text for "create"/"edit" (including frontmatter).
            old_string: Text to find for "patch".
            new_string: Replacement text for "patch".

        Returns:
            A status message.
        """
        try:
            if action == "create":
                if not content:
                    return "Error: content is required for 'create'."
                fm, body = self._svc.parse_skill_md_from_text(content)
                target_name = fm.get("name", name)
                # Idempotent: if a prior (partially-successful) review
                # already created this skill, don't error out on retry.
                if self._svc.find_skill_dir(target_name):
                    return f"Skill '{target_name}' already exists; skipping create."
                result = self._svc.create_skill(
                    name=target_name,
                    description=fm.get("description", ""),
                    agent_type=fm.get("agent_type", self.agent_type),
                    content=body.strip(),
                    tags=fm.get("tags", []),
                    created_by="agent",
                )
                self._logger.log_event(
                    "skill_created", result.name, result.agent_type,
                    self._conversation_id,
                )
                return f"Skill '{result.name}' created successfully."

            elif action == "patch":
                if not old_string or new_string is None:
                    return "Error: old_string and new_string required for 'patch'."
                detail = self._svc.get_skill(name)
                if not detail:
                    return f"Skill '{name}' not found."
                if old_string not in detail.content:
                    return f"old_string not found in skill '{name}'."
                new_content = detail.content.replace(old_string, new_string, 1)
                result = self._svc.update_skill(name, content=new_content)
                self._logger.log_event(
                    "skill_patched", name, result.agent_type,
                    self._conversation_id, extra={"version": result.version},
                )
                return f"Skill '{name}' patched (v{result.version})."

            elif action == "edit":
                if not content:
                    return "Error: content is required for 'edit'."
                fm, body = self._svc.parse_skill_md_from_text(content)
                existing = self._svc.get_skill(name)
                if not existing:
                    return f"Skill '{name}' not found."
                new_agent_type = fm.get("agent_type")
                if new_agent_type and new_agent_type != existing.agent_type:
                    return (
                        f"Error: agent_type of skill '{name}' cannot be changed "
                        f"via edit (current: {existing.agent_type}). Delete and "
                        f"recreate the skill if you really need to move it."
                    )
                result = self._svc.update_skill(
                    name,
                    description=fm.get("description"),
                    content=body.strip(),
                    tags=fm.get("tags"),
                )
                self._logger.log_event(
                    "skill_patched", name, result.agent_type,
                    self._conversation_id, extra={"version": result.version},
                )
                return f"Skill '{name}' updated (v{result.version})."

            elif action == "delete":
                self._svc.delete_skill(name)
                self._logger.log_event(
                    "skill_deleted", name, self.agent_type, self._conversation_id
                )
                return f"Skill '{name}' deleted."

            else:
                return f"Unknown action '{action}'. Use: create, patch, edit, delete."

        except Exception as e:
            return f"Error: {e}"

    def mark_insight(self, summary: str, context: str = "") -> str:
        """Record an observation about an effective approach or pitfall.

        Call this when you discover something useful during task execution:
        - A retry with a different approach succeeded
        - You found a pitfall or workaround
        - An existing skill was wrong or incomplete

        The insight will be reviewed after task completion and may become
        a new skill or improve an existing one.

        Args:
            summary: Brief description of what you learned.
            context: Additional context about the task.

        Returns:
            Confirmation message.
        """
        self._logger.write_insight(
            self.agent_type, summary, context, self._conversation_id
        )

        self._emit_event("insight_marked", {
            "agent": self.agent_type, "summary": summary[:200],
        })

        return f"Insight recorded: {summary[:80]}"

    def get_tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(self.skill_view),
            FunctionTool(self.skill_manage),
            FunctionTool(self.mark_insight),
        ]
