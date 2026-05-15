"""Per-round step trace for a chat conversation.

Captures the time-ordered sequence of skill loads, tool calls, and
mark_insight annotations within a single chat round. The Task Judge and
Skill Miner consume these traces to (a) attribute failure to the most
likely culprit skill and (b) abstract repeatable trajectories into new
skills.

Storage layout:
    ~/.cape-agent/skills/.trace/<conversation_id>/<round_idx>.jsonl

Each line is a JSON-serialised `StepTraceEntry`.
"""

from __future__ import annotations

import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.models.skill_schemas import StepTraceEntry

TRACE_ROOT = Path.home() / ".cape-agent" / "skills" / ".trace"

# Per-conversation cap on retained rounds. Older rounds are pruned to
# keep disk usage bounded. 50 is enough for any practical session.
MAX_ROUNDS_PER_CONVERSATION = 50

# Hard cap on the number of conversations retained on disk. LRU by
# directory mtime. Avoids unbounded growth across long-lived deployments.
MAX_CONVERSATIONS = 200


class StepTracer:
    def __init__(self, root: Path | None = None):
        self._root = root or TRACE_ROOT

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _round_path(self, conversation_id: str, round_idx: int) -> Path:
        return self._root / conversation_id / f"{round_idx:04d}.jsonl"

    def _conversation_dir(self, conversation_id: str) -> Path:
        return self._root / conversation_id

    def append(
        self,
        conversation_id: str,
        round_idx: int,
        entry: StepTraceEntry,
    ) -> None:
        """Append one step entry to the round's trace file under a lock."""
        path = self._round_path(conversation_id, round_idx)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry.model_dump(), ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(line + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def record_skill_loaded(
        self,
        conversation_id: str,
        round_idx: int,
        skill: str,
    ) -> None:
        self.append(
            conversation_id,
            round_idx,
            StepTraceEntry(
                ts=self._now_iso(),
                kind="skill_loaded",
                skill_in_focus=skill,
            ),
        )

    def record_tool_call(
        self,
        conversation_id: str,
        round_idx: int,
        tool_name: str,
        args_summary: Optional[str] = None,
        skill_in_focus: Optional[str] = None,
    ) -> None:
        self.append(
            conversation_id,
            round_idx,
            StepTraceEntry(
                ts=self._now_iso(),
                kind="tool_call",
                tool_name=tool_name,
                tool_args_summary=args_summary,
                skill_in_focus=skill_in_focus,
            ),
        )

    def record_tool_result(
        self,
        conversation_id: str,
        round_idx: int,
        tool_name: str,
        result_summary: Optional[str] = None,
        was_error: bool = False,
        skill_in_focus: Optional[str] = None,
    ) -> None:
        self.append(
            conversation_id,
            round_idx,
            StepTraceEntry(
                ts=self._now_iso(),
                kind="tool_result",
                tool_name=tool_name,
                tool_result_summary=result_summary,
                was_error=was_error,
                skill_in_focus=skill_in_focus,
            ),
        )

    def record_annotation(
        self,
        conversation_id: str,
        round_idx: int,
        summary: str,
        context: str = "",
        skill_in_focus: Optional[str] = None,
    ) -> None:
        """Records a mark_insight annotation as part of the trace.

        With BS-5 mark_insight becomes a trace annotation, not a skill
        creation trigger. The annotation rides alongside the trajectory
        for the Miner to consume.
        """
        self.append(
            conversation_id,
            round_idx,
            StepTraceEntry(
                ts=self._now_iso(),
                kind="annotation",
                annotation_summary=summary,
                annotation_context=context or None,
                skill_in_focus=skill_in_focus,
            ),
        )

    def read_round(
        self, conversation_id: str, round_idx: int
    ) -> list[StepTraceEntry]:
        path = self._round_path(conversation_id, round_idx)
        if not path.exists():
            return []
        entries: list[StepTraceEntry] = []
        for line in path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                entries.append(StepTraceEntry(**json.loads(line)))
            except (json.JSONDecodeError, ValueError):
                continue
        return entries

    def list_rounds(self, conversation_id: str) -> list[int]:
        d = self._conversation_dir(conversation_id)
        if not d.is_dir():
            return []
        rounds: list[int] = []
        for child in d.iterdir():
            if child.suffix != ".jsonl":
                continue
            stem = child.stem
            try:
                rounds.append(int(stem))
            except ValueError:
                continue
        return sorted(rounds)

    def skills_used_in_round(
        self, conversation_id: str, round_idx: int
    ) -> list[str]:
        """All skill names that appeared in this round's trace."""
        seen: set[str] = set()
        order: list[str] = []
        for entry in self.read_round(conversation_id, round_idx):
            if entry.skill_in_focus and entry.skill_in_focus not in seen:
                seen.add(entry.skill_in_focus)
                order.append(entry.skill_in_focus)
        return order

    def gc(self) -> None:
        """Prune old conversations and excess rounds. Safe to call often."""
        if not self._root.is_dir():
            return
        # Prune rounds within each conversation
        for conv_dir in self._root.iterdir():
            if not conv_dir.is_dir():
                continue
            rounds = sorted(
                (p for p in conv_dir.iterdir() if p.suffix == ".jsonl"),
                key=lambda p: p.name,
            )
            excess = len(rounds) - MAX_ROUNDS_PER_CONVERSATION
            if excess > 0:
                for old in rounds[:excess]:
                    try:
                        old.unlink()
                    except OSError:
                        pass
        # Prune conversations LRU by dir mtime
        conv_dirs = [p for p in self._root.iterdir() if p.is_dir()]
        if len(conv_dirs) > MAX_CONVERSATIONS:
            conv_dirs.sort(key=lambda p: p.stat().st_mtime)
            for old in conv_dirs[: len(conv_dirs) - MAX_CONVERSATIONS]:
                try:
                    for child in old.rglob("*"):
                        if child.is_file():
                            child.unlink()
                    old.rmdir()
                except OSError:
                    pass


# Module-level singleton
step_tracer = StepTracer()
