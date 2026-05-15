"""Recurrence tracker for task signatures.

The Skill Miner uses this to decide whether a user has hit the *same*
class of task multiple times — one of the three Miner triggers. We
keep this in its own tiny module so signature recording can happen
from the post-task evolution path without growing SkillLogger further.

Storage: ~/.cape-agent/skills/.log/signatures.jsonl
Each line: {"signature": str, "domain": str, "conversation_id": str, "ts": str}
"""

from __future__ import annotations

import fcntl
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

SIGNATURES_LOG = Path.home() / ".cape-agent" / "skills" / ".log" / "signatures.jsonl"


class SignatureLog:
    def __init__(self, path: Path | None = None):
        self._path = path or SIGNATURES_LOG

    def record(
        self,
        signature: str,
        domain: str,
        conversation_id: Optional[str] = None,
    ) -> None:
        if not signature:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "signature": signature.strip().lower(),
            "domain": (domain or "").strip().lower(),
            "conversation_id": conversation_id,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        line = json.dumps(entry, ensure_ascii=False)
        with open(self._path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(line + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def count_recent(
        self,
        signature: str,
        days: int = 30,
        exclude_conversation_id: Optional[str] = None,
    ) -> int:
        """Count how often `signature` has appeared in the last `days`.

        If `exclude_conversation_id` is provided, entries from that
        conversation are not counted. This lets the Miner avoid
        treating "the user mentioned it twice in the same chat" as
        recurrence.
        """
        if not signature or not self._path.exists():
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        needle = signature.strip().lower()
        count = 0
        for line in self._path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("signature") != needle:
                continue
            if (
                exclude_conversation_id
                and entry.get("conversation_id") == exclude_conversation_id
            ):
                continue
            try:
                ts = datetime.fromisoformat(entry["ts"])
            except (KeyError, ValueError):
                continue
            if ts < cutoff:
                continue
            count += 1
        return count


# Module-level singleton
signature_log = SignatureLog()
