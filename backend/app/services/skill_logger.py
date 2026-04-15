from __future__ import annotations

import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path

SKILLS_LOG_DIR = Path.home() / ".cape-agent" / "skills" / ".log"


class SkillLogger:
    def __init__(self, log_dir: Path | None = None):
        self.log_dir: Path = log_dir or SKILLS_LOG_DIR
        self._stats_path = self.log_dir / "stats.json"
        self._insights_path = self.log_dir / "insights-pending.jsonl"

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _locked_append(self, path: Path, line: str) -> None:
        """Append a single line to `path` under an exclusive file lock."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(line + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def log_event(
        self,
        event: str,
        skill: str,
        agent_type: str,
        conversation_id: str | None = None,
        extra: dict | None = None,
    ) -> None:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        events_file = self.log_dir / month / "events.jsonl"

        entry = {
            "event": event,
            "skill": skill,
            "agent_type": agent_type,
            "conversation_id": conversation_id,
            "ts": self._now_iso(),
        }
        if extra:
            entry.update(extra)

        self._locked_append(events_file, json.dumps(entry, ensure_ascii=False))
        self._update_stats(event, skill)

    def _load_stats(self) -> dict:
        if not self._stats_path.exists():
            return {}
        try:
            return json.loads(self._stats_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _update_stats(self, event: str, skill: str) -> None:
        """Read-modify-write of stats.json under an exclusive lock.

        The lock file is a sibling of stats.json so locking works even when
        stats.json itself is being recreated.
        """
        self.log_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self._stats_path.with_suffix(".json.lock")
        with open(lock_path, "a+", encoding="utf-8") as lockf:
            fcntl.flock(lockf, fcntl.LOCK_EX)
            try:
                stats = self._load_stats()
                entry = stats.setdefault(skill, {"loads": 0, "patches": 0, "last_used": None})
                if event == "skill_loaded":
                    entry["loads"] += 1
                    entry["last_used"] = self._now_iso()
                elif event == "skill_patched":
                    entry["patches"] += 1
                self._stats_path.write_text(
                    json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            finally:
                fcntl.flock(lockf, fcntl.LOCK_UN)

    def get_stats(self) -> dict:
        return self._load_stats()

    def write_insight(
        self,
        agent_type: str,
        summary: str,
        context: str,
        conversation_id: str,
    ) -> None:
        entry = {
            "agent_type": agent_type,
            "summary": summary,
            "context": context,
            "conversation_id": conversation_id,
            "timestamp": self._now_iso(),
        }
        self._locked_append(
            self._insights_path, json.dumps(entry, ensure_ascii=False)
        )

    def read_pending_insights(self, conversation_id: str) -> list[dict]:
        if not self._insights_path.exists():
            return []
        results = []
        for line in self._insights_path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("conversation_id") == conversation_id:
                results.append(entry)
        return results

    def clear_insights(self, conversation_id: str) -> None:
        """Rewrite insights-pending.jsonl without entries for the given
        conversation. Read, filter, and rewrite happen under a single
        exclusive lock so concurrent writers cannot slip in between.
        """
        if not self._insights_path.exists():
            return
        with open(self._insights_path, "r+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                lines = f.read().strip().split("\n")
                remaining = []
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("conversation_id") != conversation_id:
                        remaining.append(line)
                f.seek(0)
                f.truncate()
                for line in remaining:
                    f.write(line + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)


# Module-level singleton
skill_logger = SkillLogger()
