from __future__ import annotations

import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path

SKILLS_LOG_DIR = Path.home() / ".cape-agent" / "skills" / ".log"


class SkillLogger:
    def __init__(self, log_dir: Path | None = None):
        self._dir = log_dir or SKILLS_LOG_DIR
        self._stats_path = self._dir / "stats.json"
        self._insights_path = self._dir / "insights-pending.jsonl"

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def log_event(
        self,
        event: str,
        skill: str,
        agent_type: str,
        conversation_id: str | None = None,
        extra: dict | None = None,
    ) -> None:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        month_dir = self._dir / month
        month_dir.mkdir(parents=True, exist_ok=True)
        events_file = month_dir / "events.jsonl"

        entry = {
            "event": event,
            "skill": skill,
            "agent_type": agent_type,
            "conversation_id": conversation_id,
            "ts": self._now_iso(),
        }
        if extra:
            entry.update(extra)

        with open(events_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        self._update_stats(event, skill)

    def _load_stats(self) -> dict:
        if not self._stats_path.exists():
            return {}
        try:
            return json.loads(self._stats_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_stats(self, stats: dict) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._stats_path.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _update_stats(self, event: str, skill: str) -> None:
        stats = self._load_stats()
        entry = stats.setdefault(skill, {"loads": 0, "patches": 0, "last_used": None})
        if event == "skill_loaded":
            entry["loads"] += 1
            entry["last_used"] = self._now_iso()
        elif event == "skill_patched":
            entry["patches"] += 1
        elif event == "skill_created":
            pass
        self._save_stats(stats)

    def get_stats(self) -> dict:
        return self._load_stats()

    def write_insight(
        self,
        agent_type: str,
        summary: str,
        context: str,
        conversation_id: str,
    ) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "agent_type": agent_type,
            "summary": summary,
            "context": context,
            "conversation_id": conversation_id,
            "timestamp": self._now_iso(),
        }
        with open(self._insights_path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            fcntl.flock(f, fcntl.LOCK_UN)

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
        if not self._insights_path.exists():
            return
        lines = self._insights_path.read_text(encoding="utf-8").strip().split("\n")
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
        with open(self._insights_path, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            for line in remaining:
                f.write(line + "\n")
            fcntl.flock(f, fcntl.LOCK_UN)


# Module-level singleton
skill_logger = SkillLogger()
