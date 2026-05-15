from __future__ import annotations

import fcntl
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

SKILLS_LOG_DIR = Path.home() / ".cape-agent" / "skills" / ".log"

# Cap for the FIFO outcome lists in stats.json. Big enough to compute
# a meaningful 30-day window for a frequently-used skill, small enough
# to keep the file readable and bounded.
RECENT_OUTCOMES_CAP = 50


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

    def _default_stats_entry(self) -> dict:
        return {
            "loads": 0,
            "patches": 0,
            "last_used": None,
            "n_succ": 0,
            "n_fail": 0,
            "last_succ_at": None,
            "last_fail_at": None,
            "recent_succ": [],
            "recent_fail": [],
        }

    def _ensure_entry(self, stats: dict, skill: str) -> dict:
        entry = stats.setdefault(skill, self._default_stats_entry())
        # Migrate older entries that lack the utility fields.
        for k, v in self._default_stats_entry().items():
            entry.setdefault(k, v)
        return entry

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
                entry = self._ensure_entry(stats, skill)
                now = self._now_iso()
                if event == "skill_loaded":
                    entry["loads"] += 1
                    entry["last_used"] = now
                elif event == "skill_patched":
                    entry["patches"] += 1
                self._stats_path.write_text(
                    json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            finally:
                fcntl.flock(lockf, fcntl.LOCK_UN)

    # ── utility / outcome tracking ─────────────────────────────────

    def record_outcome(
        self,
        skill: str,
        success: bool,
        agent_type: str = "browser",
        conversation_id: Optional[str] = None,
        failure_reason: Optional[str] = None,
    ) -> None:
        """Persist a single skill outcome from a Judge result.

        Writes both an events.jsonl entry (audit log) and updates the
        per-skill counters in stats.json (read-modify-write under lock).
        """
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        events_file = self.log_dir / month / "events.jsonl"
        now = self._now_iso()
        event_name = "skill_succeeded" if success else "skill_failed"

        audit_entry: dict = {
            "event": event_name,
            "skill": skill,
            "agent_type": agent_type,
            "conversation_id": conversation_id,
            "ts": now,
        }
        if failure_reason:
            audit_entry["failure_reason"] = failure_reason
        self._locked_append(events_file, json.dumps(audit_entry, ensure_ascii=False))

        self.log_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self._stats_path.with_suffix(".json.lock")
        with open(lock_path, "a+", encoding="utf-8") as lockf:
            fcntl.flock(lockf, fcntl.LOCK_EX)
            try:
                stats = self._load_stats()
                entry = self._ensure_entry(stats, skill)
                if success:
                    entry["n_succ"] += 1
                    entry["last_succ_at"] = now
                    entry["recent_succ"].append(now)
                    if len(entry["recent_succ"]) > RECENT_OUTCOMES_CAP:
                        entry["recent_succ"] = entry["recent_succ"][-RECENT_OUTCOMES_CAP:]
                else:
                    entry["n_fail"] += 1
                    entry["last_fail_at"] = now
                    entry["recent_fail"].append(now)
                    if len(entry["recent_fail"]) > RECENT_OUTCOMES_CAP:
                        entry["recent_fail"] = entry["recent_fail"][-RECENT_OUTCOMES_CAP:]
                self._stats_path.write_text(
                    json.dumps(stats, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            finally:
                fcntl.flock(lockf, fcntl.LOCK_UN)

    def get_stats(self) -> dict:
        return self._load_stats()

    def get_skill_stats(self, skill: str) -> dict:
        """Return the raw stats entry for one skill, with defaults filled."""
        stats = self._load_stats()
        return self._ensure_entry(stats, skill).copy()

    @staticmethod
    def compute_utility(entry: dict, alpha: float = 1.0, beta: float = 1.0) -> float:
        """Laplace-smoothed all-time utility = (succ + α) / (succ + fail + α + β).

        With α = β = 1, a brand-new skill starts at 0.5, and the estimate
        converges to the empirical success rate as samples accumulate.
        """
        s = entry.get("n_succ", 0)
        f = entry.get("n_fail", 0)
        return (s + alpha) / (s + f + alpha + beta)

    @staticmethod
    def compute_recent_utility(
        entry: dict,
        days: int = 30,
        alpha: float = 1.0,
        beta: float = 1.0,
    ) -> float:
        """Laplace-smoothed utility over a rolling time window.

        Counts entries in `recent_succ`/`recent_fail` whose timestamp is
        within `days` of now. If the window is empty falls back to all-time
        utility so callers don't have to special-case it.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        def _in_window(ts_list: list) -> int:
            count = 0
            for ts in ts_list:
                try:
                    if datetime.fromisoformat(ts) >= cutoff:
                        count += 1
                except ValueError:
                    continue
            return count

        s = _in_window(entry.get("recent_succ", []))
        f = _in_window(entry.get("recent_fail", []))
        if s + f == 0:
            return SkillLogger.compute_utility(entry, alpha, beta)
        return (s + alpha) / (s + f + alpha + beta)

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
