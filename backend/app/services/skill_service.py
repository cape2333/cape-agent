from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.models.skill_schemas import SkillDetail, SkillMeta

VALID_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
MAX_NAME_LEN = 64
MAX_DESC_LEN = 512
MAX_CONTENT_CHARS = 50_000

SKILLS_ROOT = Path.home() / ".cape-agent" / "skills"

AGENT_TYPES = ("browser", "developer", "document")


class SkillService:
    def __init__(self, skills_dir: Path | None = None):
        self._dir = skills_dir or SKILLS_ROOT
        self._snapshot_path = self._dir / ".snapshot.json"

    # ── helpers ──────────────────────────────────────────────────

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _validate_name(self, name: str) -> None:
        if not name or len(name) > MAX_NAME_LEN or not VALID_NAME_RE.match(name):
            raise ValueError(
                f"Invalid skill name '{name}'. Use lowercase letters, "
                "numbers, hyphens, dots, underscores. Max 64 chars."
            )

    def find_skill_dir(self, name: str) -> Path | None:
        for agent_type in AGENT_TYPES:
            candidate = self._dir / agent_type / name
            if (candidate / "SKILL.md").exists():
                return candidate
        return None

    def resolve_skill_file(self, name: str, file_path: str) -> Path | None:
        """Safely resolve a supporting-file path inside a skill.

        Returns the resolved Path only if it stays inside the skill's
        directory after normalization. Returns None if the skill does not
        exist, the path escapes via "..", or the path is otherwise invalid.
        SKILL.md itself is also excluded — the metadata file is edited
        through update_skill, not the files API.
        """
        skill_dir = self.find_skill_dir(name)
        if not skill_dir:
            return None
        try:
            skill_dir_resolved = skill_dir.resolve()
            target = (skill_dir / file_path).resolve()
        except (OSError, RuntimeError, ValueError):
            return None
        if not target.is_relative_to(skill_dir_resolved):
            return None
        if target == skill_dir_resolved / "SKILL.md":
            return None
        return target

    def _parse_skill_md(self, path: Path) -> tuple[dict, str]:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return {}, text
        # Find the closing --- after the opening ---
        rest = text[3:]
        end = re.search(r"\n---\s*\n", rest)
        if not end:
            return {}, text
        yaml_str = rest[: end.start()]
        body = rest[end.end() :]
        try:
            fm = yaml.safe_load(yaml_str)
        except yaml.YAMLError:
            fm = {}
        return (fm if isinstance(fm, dict) else {}), body

    def parse_skill_md_from_text(self, text: str) -> tuple[dict, str]:
        """Parse a raw SKILL.md string into (frontmatter_dict, body).

        Same logic as _parse_skill_md but accepts text instead of a Path.
        """
        if not text.startswith("---"):
            return {}, text
        end = re.search(r"\n---\s*\n", text[3:])
        if not end:
            return {}, text
        yaml_str = text[3 : end.start() + 3]
        body = text[end.end() + 3 :]
        try:
            fm = yaml.safe_load(yaml_str)
        except yaml.YAMLError:
            fm = {}
        return (fm if isinstance(fm, dict) else {}), body

    def _build_skill_md(self, fm: dict, body: str) -> str:
        yaml_str = yaml.dump(
            fm, default_flow_style=False, allow_unicode=True, sort_keys=False
        )
        return f"---\n{yaml_str}---\n\n{body}"

    def _meta_from_fm(self, fm: dict) -> SkillMeta:
        return SkillMeta(
            name=fm.get("name", ""),
            description=fm.get("description", ""),
            agent_type=fm.get("agent_type", "browser"),
            version=fm.get("version", 1),
            enabled=fm.get("enabled", True),
            created_by=fm.get("created_by", "user"),
            created_at=fm.get("created_at", ""),
            updated_at=fm.get("updated_at", ""),
            tags=fm.get("tags", []),
            risk_level=fm.get("risk_level", "low"),
            dry_run_stop_at=fm.get("dry_run_stop_at"),
            is_probationary=fm.get("is_probationary", False),
        )

    def _list_supporting_files(self, skill_dir: Path) -> list[str]:
        files = []
        for subdir in ("references", "templates", "scripts"):
            d = skill_dir / subdir
            if d.is_dir():
                for f in sorted(d.rglob("*")):
                    if f.is_file():
                        files.append(str(f.relative_to(skill_dir)))
        return files

    # ── snapshot ─────────────────────────────────────────────────

    def _build_manifest(self) -> dict[str, str]:
        manifest: dict[str, str] = {}
        for agent_type in AGENT_TYPES:
            type_dir = self._dir / agent_type
            if not type_dir.is_dir():
                continue
            for skill_dir in sorted(type_dir.iterdir()):
                md = skill_dir / "SKILL.md"
                if md.is_file():
                    st = md.stat()
                    key = f"{agent_type}/{skill_dir.name}/SKILL.md"
                    manifest[key] = f"{st.st_mtime_ns}:{st.st_size}"
        return manifest

    def _is_snapshot_stale(self, snapshot: dict) -> bool:
        old_manifest = snapshot.get("manifest", {})
        new_manifest = self._build_manifest()
        return old_manifest != new_manifest

    @contextmanager
    def _snapshot_lock(self):
        """Exclusive lock around snapshot read/write/invalidate.

        The lock file is a sibling of the snapshot so locking works even
        when the snapshot itself is being recreated or deleted.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        lock_path = self._snapshot_path.with_suffix(".json.lock")
        with open(lock_path, "a+", encoding="utf-8") as lockf:
            fcntl.flock(lockf, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lockf, fcntl.LOCK_UN)

    def _load_snapshot(self) -> dict | None:
        if not self._snapshot_path.exists():
            return None
        try:
            return json.loads(self._snapshot_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _save_snapshot(self, skills: list[SkillMeta]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        data = {
            "generated_at": self._now_iso(),
            "manifest": self._build_manifest(),
            "skills": [s.model_dump() for s in skills],
        }
        tmp_path = self._snapshot_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp_path, self._snapshot_path)

    def _invalidate_snapshot(self) -> None:
        with self._snapshot_lock():
            try:
                self._snapshot_path.unlink()
            except FileNotFoundError:
                pass

    # ── CRUD ─────────────────────────────────────────────────────

    def create_skill(
        self,
        name: str,
        description: str,
        agent_type: str,
        content: str,
        tags: list[str] | None = None,
        created_by: str = "user",
    ) -> SkillMeta:
        self._validate_name(name)
        if self.find_skill_dir(name):
            raise ValueError(f"Skill '{name}' already exists.")
        if len(description) > MAX_DESC_LEN:
            raise ValueError(f"Description exceeds {MAX_DESC_LEN} chars.")
        if len(content) > MAX_CONTENT_CHARS:
            raise ValueError(f"Content exceeds {MAX_CONTENT_CHARS} chars.")

        now = self._now_iso()
        fm = {
            "name": name,
            "description": description,
            "agent_type": agent_type,
            "version": 1,
            "enabled": True,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
            "tags": tags or [],
        }
        skill_dir = self._dir / agent_type / name
        created_new_dir = not skill_dir.exists()
        skill_dir.mkdir(parents=True, exist_ok=True)
        md_path = skill_dir / "SKILL.md"
        try:
            md_path.write_text(
                self._build_skill_md(fm, content), encoding="utf-8"
            )
        except Exception:
            # Don't leave a half-initialized skill directory on disk.
            if created_new_dir:
                shutil.rmtree(skill_dir, ignore_errors=True)
            raise
        self._invalidate_snapshot()
        return self._meta_from_fm(fm)

    def list_skills(
        self,
        agent_type: str | None = None,
        enabled: bool | None = None,
        tag: str | None = None,
    ) -> list[SkillMeta]:
        with self._snapshot_lock():
            snapshot = self._load_snapshot()
            if snapshot and not self._is_snapshot_stale(snapshot):
                skills = [SkillMeta(**s) for s in snapshot["skills"]]
            else:
                skills = self._scan_all()
                self._save_snapshot(skills)

        if agent_type:
            skills = [s for s in skills if s.agent_type == agent_type]
        if enabled is not None:
            skills = [s for s in skills if s.enabled == enabled]
        if tag:
            skills = [s for s in skills if tag in s.tags]
        return skills

    def _scan_all(self) -> list[SkillMeta]:
        skills = []
        for agent_type in AGENT_TYPES:
            type_dir = self._dir / agent_type
            if not type_dir.is_dir():
                continue
            for skill_dir in sorted(type_dir.iterdir()):
                md = skill_dir / "SKILL.md"
                if not md.is_file():
                    continue
                fm, _ = self._parse_skill_md(md)
                if fm:
                    skills.append(self._meta_from_fm(fm))
        return skills

    def get_skill(self, name: str) -> SkillDetail | None:
        skill_dir = self.find_skill_dir(name)
        if not skill_dir:
            return None
        md_path = skill_dir / "SKILL.md"
        fm, body = self._parse_skill_md(md_path)
        meta = self._meta_from_fm(fm)
        return SkillDetail(
            **meta.model_dump(),
            content=body.strip(),
            raw=md_path.read_text(encoding="utf-8"),
            files=self._list_supporting_files(skill_dir),
        )

    def update_skill(
        self,
        name: str,
        description: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
        enabled: bool | None = None,
    ) -> SkillDetail:
        skill_dir = self.find_skill_dir(name)
        if not skill_dir:
            raise ValueError(f"Skill '{name}' not found.")
        if description is not None and len(description) > MAX_DESC_LEN:
            raise ValueError(f"Description exceeds {MAX_DESC_LEN} chars.")
        if content is not None and len(content) > MAX_CONTENT_CHARS:
            raise ValueError(f"Content exceeds {MAX_CONTENT_CHARS} chars.")
        md_path = skill_dir / "SKILL.md"
        fm, body = self._parse_skill_md(md_path)

        changed = False
        if description is not None and fm.get("description") != description:
            fm["description"] = description
            changed = True
        if content is not None and body != content:
            body = content
            changed = True
        if tags is not None and fm.get("tags") != tags:
            fm["tags"] = tags
            changed = True
        if enabled is not None and fm.get("enabled") != enabled:
            fm["enabled"] = enabled
            changed = True

        if changed:
            fm["version"] = fm.get("version", 1) + 1
            fm["updated_at"] = self._now_iso()
            md_path.write_text(self._build_skill_md(fm, body), encoding="utf-8")
            self._invalidate_snapshot()

        # Return SkillDetail so callers can inspect content after update
        meta = self._meta_from_fm(fm)
        return SkillDetail(
            **meta.model_dump(),
            content=body.strip(),
            raw=md_path.read_text(encoding="utf-8"),
            files=self._list_supporting_files(skill_dir),
        )

    def delete_skill(self, name: str) -> None:
        skill_dir = self.find_skill_dir(name)
        if not skill_dir:
            raise ValueError(f"Skill '{name}' not found.")
        shutil.rmtree(skill_dir)
        self._invalidate_snapshot()

    def build_skill_prompt_block(self, agent_type: str) -> str:
        """Build the system prompt skill index block for an agent type."""
        skills = self.list_skills(agent_type=agent_type, enabled=True)
        if not skills:
            return ""
        lines = []
        for s in skills:
            lines.append(f"- {s.name}: {s.description}")
        index = "\n".join(lines)
        return (
            "\n\n## Available Skills\n\n"
            "Before executing your task, scan the skills below. If any skill matches\n"
            "your current task, load it with skill_view(name) and follow its instructions.\n\n"
            f"<available_skills>\n{index}\n</available_skills>\n\n"
            "If a skill you used was wrong or incomplete, update it with skill_manage.\n\n"
            "## When to call mark_insight\n\n"
            "mark_insight is a free-form annotation channel. It does NOT create or\n"
            "modify skills directly — annotations ride alongside your trajectory and\n"
            "are reviewed automatically after the task. Call it whenever you notice\n"
            "something the raw trace would not reveal:\n"
            "- A non-obvious mechanism (\"this click is silently swallowed the first time\")\n"
            "- A hidden constraint (\"the API rate-limits with HTTP 200 + empty body\")\n"
            "- A user-preference observation (\"when they say 'cheapest' they mean total\n"
            "  including baggage\")\n"
            "- A subtle pitfall in an existing skill\n\n"
            "Annotate freely — the system decides what becomes a skill. Do NOT stop to\n"
            "create a skill yourself; just record what you saw and keep going."
        )


# Module-level singleton
skill_service = SkillService()
