# Skill Self-Evolution System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable Cape Agent's workforce agents (browser, developer, document) to create, improve, and reuse skills through continuous usage, with a full management UI.

**Architecture:** File-based skill storage at `~/.cape-agent/skills/{agent_type}/{skill-name}/SKILL.md` with YAML frontmatter. Backend services handle CRUD, snapshot caching, insight logging, and post-task background review. Frontend provides full skill management pages via new React routes.

**Tech Stack:** Python/FastAPI (backend services + API), CAMEL-AI FunctionTool (agent toolkit), React/Zustand/Tailwind (frontend), YAML frontmatter + Markdown (skill format), JSON Lines (logging).

**Spec:** `docs/superpowers/specs/2026-04-15-skill-evolution-design.md`

---

### Task 1: Pydantic Models for Skills

**Files:**
- Create: `backend/app/models/skill_schemas.py`

- [ ] **Step 1: Create skill schema models**

```python
# backend/app/models/skill_schemas.py
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class SkillMeta(BaseModel):
    name: str
    description: str
    agent_type: Literal["browser", "developer", "document"]
    version: int = 1
    enabled: bool = True
    created_by: Literal["agent", "user"] = "user"
    created_at: str = ""
    updated_at: str = ""
    tags: list[str] = Field(default_factory=list)


class SkillDetail(SkillMeta):
    content: str = ""
    raw: str = ""
    files: list[str] = Field(default_factory=list)


class SkillCreate(BaseModel):
    name: str
    description: str
    agent_type: Literal["browser", "developer", "document"]
    content: str
    tags: list[str] = Field(default_factory=list)


class SkillUpdate(BaseModel):
    description: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    enabled: Optional[bool] = None


class SkillStats(BaseModel):
    name: str
    loads: int = 0
    patches: int = 0
    last_used: Optional[str] = None


class SkillLogEntry(BaseModel):
    event: str
    skill: str
    agent_type: str
    conversation_id: Optional[str] = None
    timestamp: str


class InsightRecord(BaseModel):
    agent_type: Literal["browser", "developer", "document"]
    summary: str
    context: str = ""
    conversation_id: str = ""
    timestamp: str = ""
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/models/skill_schemas.py
git commit -m "feat(skills): add Pydantic models for skill system"
```

---

### Task 2: Skill Service — CRUD + Snapshot Cache

**Files:**
- Create: `backend/app/services/skill_service.py`
- Test: `backend/tests/test_skill_service.py`

- [ ] **Step 1: Write failing tests for skill service**

```python
# backend/tests/test_skill_service.py
import json
import os
import tempfile
from pathlib import Path

import pytest

from app.services.skill_service import SkillService


@pytest.fixture
def skill_dir(tmp_path):
    return tmp_path / "skills"


@pytest.fixture
def svc(skill_dir):
    return SkillService(skills_dir=skill_dir)


class TestSkillServiceCreate:
    def test_create_skill_writes_skill_md(self, svc, skill_dir):
        result = svc.create_skill(
            name="test-skill",
            description="A test skill",
            agent_type="browser",
            content="## Steps\n1. Do something",
            tags=["test"],
            created_by="user",
        )
        assert result.name == "test-skill"
        skill_md = skill_dir / "browser" / "test-skill" / "SKILL.md"
        assert skill_md.exists()
        text = skill_md.read_text()
        assert "name: test-skill" in text
        assert "## Steps" in text

    def test_create_duplicate_raises(self, svc):
        svc.create_skill(
            name="dup", description="d", agent_type="browser",
            content="body", created_by="user",
        )
        with pytest.raises(ValueError, match="already exists"):
            svc.create_skill(
                name="dup", description="d", agent_type="browser",
                content="body", created_by="user",
            )

    def test_create_invalid_name_raises(self, svc):
        with pytest.raises(ValueError, match="Invalid skill name"):
            svc.create_skill(
                name="Bad Name!", description="d", agent_type="browser",
                content="body", created_by="user",
            )


class TestSkillServiceRead:
    def test_list_skills_returns_created(self, svc):
        svc.create_skill(
            name="s1", description="d1", agent_type="browser",
            content="body", created_by="user",
        )
        svc.create_skill(
            name="s2", description="d2", agent_type="developer",
            content="body", created_by="user",
        )
        all_skills = svc.list_skills()
        assert len(all_skills) == 2

        browser_only = svc.list_skills(agent_type="browser")
        assert len(browser_only) == 1
        assert browser_only[0].name == "s1"

    def test_get_skill_detail(self, svc):
        svc.create_skill(
            name="detail-test", description="desc", agent_type="document",
            content="## Content\nHello", created_by="user",
        )
        detail = svc.get_skill("detail-test")
        assert detail is not None
        assert detail.content == "## Content\nHello"
        assert "name: detail-test" in detail.raw

    def test_get_nonexistent_returns_none(self, svc):
        assert svc.get_skill("nope") is None


class TestSkillServiceUpdate:
    def test_patch_updates_frontmatter(self, svc):
        svc.create_skill(
            name="upd", description="old", agent_type="browser",
            content="body", created_by="user",
        )
        result = svc.update_skill("upd", description="new desc")
        assert result.description == "new desc"
        assert result.version == 2

    def test_patch_content(self, svc):
        svc.create_skill(
            name="upd2", description="d", agent_type="browser",
            content="old body", created_by="user",
        )
        result = svc.update_skill("upd2", content="new body")
        assert result.content == "new body"

    def test_toggle_enabled(self, svc):
        svc.create_skill(
            name="tog", description="d", agent_type="browser",
            content="body", created_by="user",
        )
        result = svc.update_skill("tog", enabled=False)
        assert result.enabled is False


class TestSkillServiceDelete:
    def test_delete_removes_directory(self, svc, skill_dir):
        svc.create_skill(
            name="del-me", description="d", agent_type="browser",
            content="body", created_by="user",
        )
        assert (skill_dir / "browser" / "del-me").exists()
        svc.delete_skill("del-me")
        assert not (skill_dir / "browser" / "del-me").exists()

    def test_delete_nonexistent_raises(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.delete_skill("nope")


class TestSnapshot:
    def test_snapshot_created_on_list(self, svc, skill_dir):
        svc.create_skill(
            name="snap", description="d", agent_type="browser",
            content="body", created_by="user",
        )
        svc.list_skills()
        snapshot_path = skill_dir / ".snapshot.json"
        assert snapshot_path.exists()
        data = json.loads(snapshot_path.read_text())
        assert len(data["skills"]) == 1
        assert data["skills"][0]["name"] == "snap"

    def test_snapshot_reused_when_fresh(self, svc, skill_dir):
        svc.create_skill(
            name="cached", description="d", agent_type="browser",
            content="body", created_by="user",
        )
        svc.list_skills()  # builds snapshot
        # Modify snapshot to prove it's being read from cache
        snapshot_path = skill_dir / ".snapshot.json"
        data = json.loads(snapshot_path.read_text())
        data["skills"][0]["description"] = "from-cache"
        snapshot_path.write_text(json.dumps(data))
        result = svc.list_skills()
        assert result[0].description == "from-cache"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
python -m pytest tests/test_skill_service.py -v
```

Expected: FAIL — `app.services.skill_service` does not exist yet.

- [ ] **Step 3: Implement SkillService**

```python
# backend/app/services/skill_service.py
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from app.models.skill_schemas import SkillDetail, SkillMeta

VALID_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
MAX_NAME_LEN = 64
MAX_DESC_LEN = 512
MAX_CONTENT_CHARS = 50_000

SKILLS_ROOT = Path.home() / ".cape-agent" / "skills"


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

    def _find_skill_dir(self, name: str) -> Path | None:
        for agent_type in ("browser", "developer", "document"):
            candidate = self._dir / agent_type / name
            if (candidate / "SKILL.md").exists():
                return candidate
        return None

    def _parse_skill_md(self, path: Path) -> tuple[dict, str]:
        text = path.read_text(encoding="utf-8")
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
        yaml_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False)
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
        manifest = {}
        for agent_type in ("browser", "developer", "document"):
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
        self._snapshot_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _invalidate_snapshot(self) -> None:
        if self._snapshot_path.exists():
            self._snapshot_path.unlink()

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
        if self._find_skill_dir(name):
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
        skill_dir.mkdir(parents=True, exist_ok=True)
        md_path = skill_dir / "SKILL.md"
        md_path.write_text(self._build_skill_md(fm, content), encoding="utf-8")
        self._invalidate_snapshot()
        return self._meta_from_fm(fm)

    def list_skills(
        self,
        agent_type: str | None = None,
        enabled: bool | None = None,
        tag: str | None = None,
    ) -> list[SkillMeta]:
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
        for agent_type in ("browser", "developer", "document"):
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
        skill_dir = self._find_skill_dir(name)
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
    ) -> SkillMeta:
        skill_dir = self._find_skill_dir(name)
        if not skill_dir:
            raise ValueError(f"Skill '{name}' not found.")
        md_path = skill_dir / "SKILL.md"
        fm, body = self._parse_skill_md(md_path)

        if description is not None:
            fm["description"] = description
        if content is not None:
            body = content
        if tags is not None:
            fm["tags"] = tags
        if enabled is not None:
            fm["enabled"] = enabled

        fm["version"] = fm.get("version", 1) + 1
        fm["updated_at"] = self._now_iso()

        md_path.write_text(self._build_skill_md(fm, body), encoding="utf-8")
        self._invalidate_snapshot()
        return self._meta_from_fm(fm)

    def delete_skill(self, name: str) -> None:
        skill_dir = self._find_skill_dir(name)
        if not skill_dir:
            raise ValueError(f"Skill '{name}' not found.")
        shutil.rmtree(skill_dir)
        self._invalidate_snapshot()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
python -m pytest tests/test_skill_service.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/skill_service.py backend/tests/test_skill_service.py
git commit -m "feat(skills): add SkillService with CRUD and snapshot cache"
```

---

### Task 3: Skill Logger Service

**Files:**
- Create: `backend/app/services/skill_logger.py`
- Test: `backend/tests/test_skill_logger.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_skill_logger.py
import json
from pathlib import Path

import pytest

from app.services.skill_logger import SkillLogger


@pytest.fixture
def logger(tmp_path):
    return SkillLogger(log_dir=tmp_path / ".log")


class TestSkillLogger:
    def test_log_event_creates_monthly_file(self, logger, tmp_path):
        logger.log_event("skill_loaded", "test-skill", "browser", "conv-1")
        files = list((tmp_path / ".log").rglob("events.jsonl"))
        assert len(files) == 1
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event"] == "skill_loaded"
        assert entry["skill"] == "test-skill"

    def test_log_event_updates_stats(self, logger, tmp_path):
        logger.log_event("skill_loaded", "s1", "browser", "c1")
        logger.log_event("skill_loaded", "s1", "browser", "c2")
        logger.log_event("skill_patched", "s1", "browser", "c2")
        stats = logger.get_stats()
        assert stats["s1"]["loads"] == 2
        assert stats["s1"]["patches"] == 1

    def test_write_insight(self, logger, tmp_path):
        logger.write_insight("browser", "found a trick", "some context", "conv-1")
        pending = logger.read_pending_insights("conv-1")
        assert len(pending) == 1
        assert pending[0]["summary"] == "found a trick"

    def test_read_insights_filters_by_conversation(self, logger):
        logger.write_insight("browser", "insight A", "", "conv-1")
        logger.write_insight("browser", "insight B", "", "conv-2")
        assert len(logger.read_pending_insights("conv-1")) == 1
        assert len(logger.read_pending_insights("conv-2")) == 1

    def test_clear_insights(self, logger):
        logger.write_insight("browser", "i1", "", "conv-1")
        logger.write_insight("browser", "i2", "", "conv-2")
        logger.clear_insights("conv-1")
        assert len(logger.read_pending_insights("conv-1")) == 0
        assert len(logger.read_pending_insights("conv-2")) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
python -m pytest tests/test_skill_logger.py -v
```

Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement SkillLogger**

```python
# backend/app/services/skill_logger.py
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

    # ── event logging ───────────────────────────────────────────

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

    # ── stats ───────────────────────────────────────────────────

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
            pass  # just record existence
        self._save_stats(stats)

    def get_stats(self) -> dict:
        return self._load_stats()

    # ── insights ────────────────────────────────────────────────

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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
python -m pytest tests/test_skill_logger.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/skill_logger.py backend/tests/test_skill_logger.py
git commit -m "feat(skills): add SkillLogger for event tracking and insight recording"
```

---

### Task 4: Skill Toolkit for Agents

**Files:**
- Create: `backend/app/toolkits/skill_toolkit.py`
- Test: `backend/tests/test_skill_toolkit.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_skill_toolkit.py
import json

import pytest

from app.services.skill_service import SkillService
from app.services.skill_logger import SkillLogger
from app.toolkits.skill_toolkit import SkillToolkit


@pytest.fixture
def services(tmp_path):
    skills_dir = tmp_path / "skills"
    log_dir = skills_dir / ".log"
    svc = SkillService(skills_dir=skills_dir)
    logger = SkillLogger(log_dir=log_dir)
    return svc, logger, skills_dir


@pytest.fixture
def toolkit(services):
    svc, logger, _ = services
    return SkillToolkit(
        agent_type="browser",
        skill_service=svc,
        skill_logger=logger,
        conversation_id="conv-1",
    )


class TestSkillView:
    def test_view_existing_skill(self, toolkit, services):
        svc, _, _ = services
        svc.create_skill(
            name="my-skill", description="desc", agent_type="browser",
            content="## Steps\n1. Do it", created_by="user",
        )
        result = toolkit.skill_view("my-skill")
        assert "## Steps" in result

    def test_view_nonexistent(self, toolkit):
        result = toolkit.skill_view("nope")
        assert "not found" in result.lower()


class TestSkillManage:
    def test_create_via_manage(self, toolkit, services):
        svc, _, _ = services
        result = toolkit.skill_manage(
            action="create", name="new-one",
            content="---\nname: new-one\ndescription: test\nagent_type: browser\nversion: 1\nenabled: true\ncreated_by: agent\ncreated_at: ''\nupdated_at: ''\ntags: []\n---\n\n## Steps\nDo it",
        )
        assert "created" in result.lower() or "success" in result.lower()
        assert svc.get_skill("new-one") is not None

    def test_delete_via_manage(self, toolkit, services):
        svc, _, _ = services
        svc.create_skill(
            name="del-me", description="d", agent_type="browser",
            content="body", created_by="user",
        )
        result = toolkit.skill_manage(action="delete", name="del-me")
        assert "deleted" in result.lower()
        assert svc.get_skill("del-me") is None


class TestMarkInsight:
    def test_mark_records_insight(self, toolkit, services):
        _, logger, _ = services
        result = toolkit.mark_insight("Found a better search approach", "while searching papers")
        assert "recorded" in result.lower()
        insights = logger.read_pending_insights("conv-1")
        assert len(insights) == 1
        assert insights[0]["summary"] == "Found a better search approach"


class TestGetTools:
    def test_returns_three_tools(self, toolkit):
        tools = toolkit.get_tools()
        names = [t.get_function_name() for t in tools]
        assert "skill_view" in names
        assert "skill_manage" in names
        assert "mark_insight" in names
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
python -m pytest tests/test_skill_toolkit.py -v
```

Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement SkillToolkit**

```python
# backend/app/toolkits/skill_toolkit.py
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
    ):
        self.agent_type = agent_type
        self._svc = skill_service
        self._logger = skill_logger
        self._conversation_id = conversation_id

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

        if file_path:
            skill_dir = self._svc._find_skill_dir(name)
            if skill_dir:
                target = skill_dir / file_path
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
                fm, body = self._svc._parse_skill_md_from_text(content)
                result = self._svc.create_skill(
                    name=fm.get("name", name),
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
                new_content = detail.content.replace(old_string, new_string, 1)
                if new_content == detail.content:
                    return f"old_string not found in skill '{name}'."
                result = self._svc.update_skill(name, content=new_content)
                self._logger.log_event(
                    "skill_patched", name, result.agent_type,
                    self._conversation_id, extra={"version": result.version},
                )
                return f"Skill '{name}' patched (v{result.version})."

            elif action == "edit":
                if not content:
                    return "Error: content is required for 'edit'."
                fm, body = self._svc._parse_skill_md_from_text(content)
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
        return f"Insight recorded: {summary[:80]}"

    def get_tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(self.skill_view),
            FunctionTool(self.skill_manage),
            FunctionTool(self.mark_insight),
        ]
```

Then add a helper to SkillService for parsing raw SKILL.md text (used by `skill_manage` create/edit):

Add to `backend/app/services/skill_service.py`:

```python
    def _parse_skill_md_from_text(self, text: str) -> tuple[dict, str]:
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
python -m pytest tests/test_skill_toolkit.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/toolkits/skill_toolkit.py backend/tests/test_skill_toolkit.py backend/app/services/skill_service.py
git commit -m "feat(skills): add SkillToolkit with skill_view, skill_manage, mark_insight"
```

---

### Task 5: Integrate Skill Toolkit into Agent Factories

**Files:**
- Modify: `backend/app/services/skill_service.py` (add singleton)
- Modify: `backend/app/services/skill_logger.py` (add singleton)
- Modify: `backend/app/agents/factory/browser.py`
- Modify: `backend/app/agents/factory/developer.py`
- Modify: `backend/app/agents/factory/document.py`
- Modify: `backend/app/agents/factory/__init__.py`

- [ ] **Step 1: Add module-level singleton instances**

Add to the bottom of `backend/app/services/skill_service.py`:

```python
# Module-level singleton
skill_service = SkillService()
```

Add to the bottom of `backend/app/services/skill_logger.py`:

```python
# Module-level singleton
skill_logger = SkillLogger()
```

- [ ] **Step 2: Add `build_skill_prompt_block` to skill_service.py**

Add this method to `SkillService`:

```python
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
            "If a skill you used was wrong or incomplete, update it with skill_manage.\n"
            "After completing a difficult task (3+ tool calls with retries),\n"
            "consider saving the approach as a new skill.\n\n"
            "When you encounter these situations during task execution:\n"
            "- A retry with a different approach succeeded\n"
            "- You discovered a pitfall or workaround\n"
            "- An existing skill's instructions were wrong or incomplete\n\n"
            "Call mark_insight() to record what you learned.\n"
            "Do NOT stop to create a full skill — just record the observation and continue your task."
        )
```

- [ ] **Step 3: Modify browser factory**

In `backend/app/agents/factory/browser.py`, add skill toolkit integration:

```python
# Add import at top
from app.services.skill_service import skill_service
from app.services.skill_logger import skill_logger
from app.toolkits.skill_toolkit import SkillToolkit
```

Modify `create_browser_agent` to accept `conversation_id` parameter and inject skills:

```python
def create_browser_agent(
    task_lock: TaskLock, model, working_directory: str = "",
    conversation_id: str = "",
) -> ListenChatAgent:
    tools = browser_service.get_tools()

    terminal_toolkit = TerminalToolkit(
        working_directory=working_directory,
        safe_mode=True,
        clone_current_env=True,
    )
    tools = tools + terminal_toolkit.get_tools()

    tools = tools + SearchToolkit.get_can_use_tools()

    human_toolkit = HumanToolkit(task_lock, "Browser Agent")
    tools = tools + human_toolkit.get_tools()

    # Skill toolkit
    skill_toolkit = SkillToolkit(
        agent_type="browser",
        skill_service=skill_service,
        skill_logger=skill_logger,
        conversation_id=conversation_id,
    )
    tools = tools + skill_toolkit.get_tools()

    skill_block = skill_service.build_skill_prompt_block("browser")
    system_message = BROWSER_SYSTEM_PROMPT.format(
        platform_system=platform.system(),
        platform_machine=platform.machine(),
        working_directory=working_directory,
        now_str=datetime.now().strftime("%Y-%m-%d %H:%M"),
    ) + skill_block

    return ListenChatAgent(
        task_lock=task_lock,
        agent_name="Browser Agent",
        system_message=BaseMessage.make_assistant_message(
            role_name="Browser Agent",
            content=system_message,
        ),
        tools=tools,
        model=model,
        enable_snapshot_clean=True,
        prune_tool_calls_from_memory=True,
    )
```

- [ ] **Step 4: Modify developer factory**

Same pattern in `backend/app/agents/factory/developer.py`:

```python
# Add imports at top
from app.services.skill_service import skill_service
from app.services.skill_logger import skill_logger
from app.toolkits.skill_toolkit import SkillToolkit
```

Modify `create_developer_agent`:

```python
def create_developer_agent(
    task_lock: TaskLock, model, working_directory: str,
    conversation_id: str = "",
) -> ListenChatAgent:
    terminal_toolkit = TerminalToolkit(
        working_directory=working_directory,
        safe_mode=True,
        clone_current_env=True,
    )
    human_toolkit = HumanToolkit(task_lock, "Developer Agent")

    skill_toolkit = SkillToolkit(
        agent_type="developer",
        skill_service=skill_service,
        skill_logger=skill_logger,
        conversation_id=conversation_id,
    )
    tools = (
        terminal_toolkit.get_tools()
        + human_toolkit.get_tools()
        + skill_toolkit.get_tools()
    )

    skill_block = skill_service.build_skill_prompt_block("developer")
    system_message = DEVELOPER_SYSTEM_PROMPT.format(
        platform_system=platform.system(),
        platform_machine=platform.machine(),
        working_directory=working_directory,
        now_str=datetime.now().strftime("%Y-%m-%d %H:%M"),
    ) + skill_block

    return ListenChatAgent(
        task_lock=task_lock,
        agent_name="Developer Agent",
        system_message=BaseMessage.make_assistant_message(
            role_name="Developer Agent",
            content=system_message,
        ),
        tools=tools,
        model=model,
        prune_tool_calls_from_memory=True,
    )
```

- [ ] **Step 5: Modify document factory**

Same pattern in `backend/app/agents/factory/document.py`:

```python
# Add imports at top
from app.services.skill_service import skill_service
from app.services.skill_logger import skill_logger
from app.toolkits.skill_toolkit import SkillToolkit
```

Modify `create_document_agent`:

```python
def create_document_agent(
    task_lock: TaskLock, model, working_directory: str,
    conversation_id: str = "",
) -> ListenChatAgent:
    file_toolkit = FileToolkit(
        working_directory=working_directory,
        default_encoding="utf-8",
        backup_enabled=True,
    )
    excel_toolkit = ExcelToolkit()
    pptx_toolkit = PPTXToolkit()
    terminal_toolkit = TerminalToolkit(
        working_directory=working_directory,
        safe_mode=True,
        clone_current_env=True,
    )
    human_toolkit = HumanToolkit(task_lock, "Document Agent")

    skill_toolkit = SkillToolkit(
        agent_type="document",
        skill_service=skill_service,
        skill_logger=skill_logger,
        conversation_id=conversation_id,
    )
    tools = (
        file_toolkit.get_tools()
        + excel_toolkit.get_tools()
        + pptx_toolkit.get_tools()
        + terminal_toolkit.get_tools()
        + human_toolkit.get_tools()
        + skill_toolkit.get_tools()
    )

    skill_block = skill_service.build_skill_prompt_block("document")
    system_message = DOCUMENT_SYSTEM_PROMPT.format(
        platform_system=platform.system(),
        platform_machine=platform.machine(),
        working_directory=working_directory,
        now_str=datetime.now().strftime("%Y-%m-%d %H:%M"),
    ) + skill_block

    return ListenChatAgent(
        task_lock=task_lock,
        agent_name="Document Agent",
        system_message=BaseMessage.make_assistant_message(
            role_name="Document Agent",
            content=system_message,
        ),
        tools=tools,
        model=model,
        prune_tool_calls_from_memory=True,
    )
```

- [ ] **Step 6: Update `__init__.py` exports (no change needed — functions keep same names)**

Verify the factory `__init__.py` still exports correctly — the function signatures changed (added `conversation_id`) but it has a default value so existing calls still work.

- [ ] **Step 7: Pass conversation_id in build_workforce**

In `backend/app/services/agent_service.py`, update the agent creation calls inside `build_workforce()` to pass `conversation_id=task_lock.id`:

At line 508 (browser agent creation):
```python
        browser_agent = create_browser_agent(
            task_lock, browser_model, working_dir, conversation_id=task_lock.id
        )
```

At line 514 (developer agent creation):
```python
    developer_agent = create_developer_agent(
        task_lock, model, working_dir, conversation_id=task_lock.id
    )
```

At line 520 (document agent creation):
```python
    document_agent = create_document_agent(
        task_lock, model, working_dir, conversation_id=task_lock.id
    )
```

- [ ] **Step 8: Run existing tests to check no regressions**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
python -m pytest tests/ -v
```

Expected: All existing tests still PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/agents/factory/browser.py backend/app/agents/factory/developer.py backend/app/agents/factory/document.py backend/app/services/agent_service.py backend/app/services/skill_service.py backend/app/services/skill_logger.py
git commit -m "feat(skills): integrate skill toolkit into all agent factories"
```

---

### Task 6: Background Skill Reviewer

**Files:**
- Create: `backend/app/services/skill_reviewer.py`

- [ ] **Step 1: Implement skill reviewer**

```python
# backend/app/services/skill_reviewer.py
"""Post-task background review that converts pending insights into skills."""

from __future__ import annotations

import logging
from typing import Optional

from camel.agents import ChatAgent
from camel.toolkits import FunctionTool

from app.services.skill_service import SkillService, skill_service
from app.services.skill_logger import SkillLogger, skill_logger
from app.toolkits.skill_toolkit import SkillToolkit

logger = logging.getLogger(__name__)

REVIEW_PROMPT_TEMPLATE = """\
You are reviewing task execution insights to maintain the skill library.

## Task Summary
{task_summary}

## Pending Insights
{insights_text}

## Existing Skills
{existing_skills_text}

For each insight, decide:
1. If it improves an existing skill -> use skill_manage(action="patch", name="...", old_string="...", new_string="...")
2. If it's a new reusable approach -> use skill_manage(action="create", name="...", content="...")
3. If it's too specific or trivial -> skip it

Only save knowledge that will help future tasks. Be selective.
When creating a new skill, use this SKILL.md format:

---
name: skill-name
description: one-line description
agent_type: browser|developer|document
version: 1
enabled: true
created_by: agent
created_at: ''
updated_at: ''
tags: []
---

## Trigger Conditions
When to use this skill.

## Steps
1. Step one
2. Step two

## Pitfalls
- Known issues

## Verification
- How to confirm success
"""


async def review_insights(
    conversation_id: str,
    task_summary: str,
    model,
    svc: SkillService | None = None,
    log: SkillLogger | None = None,
) -> None:
    svc = svc or skill_service
    log = log or skill_logger

    insights = log.read_pending_insights(conversation_id)
    if not insights:
        return

    agent_types = list({i["agent_type"] for i in insights})
    existing = svc.list_skills()
    existing_for_types = [s for s in existing if s.agent_type in agent_types]

    insights_text = "\n".join(
        f"{i+1}. [{ins['agent_type']}] {ins['summary']}"
        + (f" (context: {ins['context']})" if ins.get("context") else "")
        for i, ins in enumerate(insights)
    )
    existing_skills_text = "\n".join(
        f"- {s.name} ({s.agent_type}): {s.description}"
        for s in existing_for_types
    ) or "(none)"

    prompt = REVIEW_PROMPT_TEMPLATE.format(
        task_summary=task_summary,
        insights_text=insights_text,
        existing_skills_text=existing_skills_text,
    )

    toolkit = SkillToolkit(
        agent_type=agent_types[0] if agent_types else "browser",
        skill_service=svc,
        skill_logger=log,
        conversation_id=conversation_id,
    )

    reviewer = ChatAgent(
        system_message="You are a skill librarian. Use the provided tools to create or update skills based on insights.",
        model=model,
        tools=toolkit.get_tools(),
    )

    try:
        await reviewer.astep(prompt)
    except Exception as e:
        logger.warning(f"Skill review failed: {e}")

    log.clear_insights(conversation_id)
    logger.info(f"Skill review completed for conversation {conversation_id}")
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/skill_reviewer.py
git commit -m "feat(skills): add background skill reviewer for post-task insight processing"
```

---

### Task 7: Wire Background Review into Chat Endpoint

**Files:**
- Modify: `backend/app/api/chat.py`

- [ ] **Step 1: Add review trigger after workforce completion**

In `backend/app/api/chat.py`, add imports at top:

```python
from app.services.skill_reviewer import review_insights
from app.services.skill_logger import skill_logger
from app.services.agent_service import build_model
```

Then, inside the `event_stream()` function, after the workforce `"end"` event block (after `yield sse_json("end", ...)` at line 162), add:

```python
                        # Trigger background skill review if insights exist
                        try:
                            pending = skill_logger.read_pending_insights(req.conversation_id)
                            if pending:
                                review_model = build_model(
                                    provider, model_name, req.api_key, req.api_base, stream=False
                                )
                                asyncio.create_task(
                                    review_insights(
                                        conversation_id=req.conversation_id,
                                        task_summary=content[:2000],
                                        model=review_model,
                                    )
                                )
                        except Exception as e:
                            logger.warning(f"Skill review trigger failed: {e}")
```

- [ ] **Step 2: Add SSE events for skill operations**

In `backend/app/toolkits/skill_toolkit.py`, emit SSE events when skills are loaded or insights are marked. This requires the toolkit to have access to `task_lock`. Update `__init__`:

```python
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
```

In `skill_view`, after `self._logger.log_event(...)`:

```python
        if self._task_lock:
            import asyncio
            try:
                asyncio.get_event_loop().create_task(
                    self._task_lock.put_event("skill_loaded", {
                        "skill": name, "agent": self.agent_type,
                    })
                )
            except Exception:
                pass
```

In `mark_insight`, after `self._logger.write_insight(...)`:

```python
        if self._task_lock:
            import asyncio
            try:
                asyncio.get_event_loop().create_task(
                    self._task_lock.put_event("insight_marked", {
                        "agent": self.agent_type, "summary": summary[:200],
                    })
                )
            except Exception:
                pass
```

Update all three factory files to pass `task_lock` to `SkillToolkit`:

```python
    skill_toolkit = SkillToolkit(
        agent_type="browser",  # or "developer" or "document"
        skill_service=skill_service,
        skill_logger=skill_logger,
        conversation_id=conversation_id,
        task_lock=task_lock,
    )
```

- [ ] **Step 3: Run all backend tests**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
python -m pytest tests/ -v
```

Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/chat.py backend/app/toolkits/skill_toolkit.py backend/app/agents/factory/browser.py backend/app/agents/factory/developer.py backend/app/agents/factory/document.py
git commit -m "feat(skills): wire background review into chat endpoint and add SSE events"
```

---

### Task 8: Backend REST API for Skills

**Files:**
- Create: `backend/app/api/skills.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Implement skills API router**

```python
# backend/app/api/skills.py
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.skill_schemas import (
    SkillCreate,
    SkillDetail,
    SkillLogEntry,
    SkillMeta,
    SkillStats,
    SkillUpdate,
)
from app.services.skill_service import skill_service
from app.services.skill_logger import skill_logger

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("", response_model=list[SkillMeta])
async def list_skills(
    agent_type: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
    tag: Optional[str] = Query(None),
):
    return skill_service.list_skills(agent_type=agent_type, enabled=enabled, tag=tag)


@router.get("/stats")
async def get_stats():
    raw = skill_logger.get_stats()
    return [
        SkillStats(name=name, **data).model_dump()
        for name, data in raw.items()
    ]


@router.get("/logs")
async def get_logs(limit: int = Query(50), skill: Optional[str] = Query(None)):
    import json
    from pathlib import Path
    from datetime import datetime, timezone

    log_dir = skill_logger._dir
    entries = []
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    events_file = log_dir / month / "events.jsonl"
    if events_file.exists():
        for line in events_file.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if skill and entry.get("skill") != skill:
                continue
            entries.append(entry)
    return entries[-limit:]


@router.get("/{name}", response_model=SkillDetail)
async def get_skill(name: str):
    detail = skill_service.get_skill(name)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    return detail


@router.post("", response_model=SkillMeta, status_code=201)
async def create_skill(req: SkillCreate):
    try:
        return skill_service.create_skill(
            name=req.name,
            description=req.description,
            agent_type=req.agent_type,
            content=req.content,
            tags=req.tags,
            created_by="user",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{name}", response_model=SkillMeta)
async def update_skill_full(name: str, req: SkillUpdate):
    try:
        return skill_service.update_skill(
            name,
            description=req.description,
            content=req.content,
            tags=req.tags,
            enabled=req.enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{name}", response_model=SkillMeta)
async def update_skill_partial(name: str, req: SkillUpdate):
    try:
        return skill_service.update_skill(
            name,
            description=req.description,
            content=req.content,
            tags=req.tags,
            enabled=req.enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{name}")
async def delete_skill(name: str):
    try:
        skill_service.delete_skill(name)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{name}/files")
async def list_skill_files(name: str):
    detail = skill_service.get_skill(name)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    return detail.files


@router.get("/{name}/files/{file_path:path}")
async def read_skill_file(name: str, file_path: str):
    skill_dir = skill_service._find_skill_dir(name)
    if not skill_dir:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    target = skill_dir / file_path
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"File '{file_path}' not found")
    return {"content": target.read_text(encoding="utf-8")}


@router.put("/{name}/files/{file_path:path}")
async def write_skill_file(name: str, file_path: str, body: dict):
    skill_dir = skill_service._find_skill_dir(name)
    if not skill_dir:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    target = skill_dir / file_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.get("content", ""), encoding="utf-8")
    return {"ok": True}


@router.delete("/{name}/files/{file_path:path}")
async def delete_skill_file(name: str, file_path: str):
    skill_dir = skill_service._find_skill_dir(name)
    if not skill_dir:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    target = skill_dir / file_path
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"File '{file_path}' not found")
    target.unlink()
    return {"ok": True}
```

- [ ] **Step 2: Register router in main.py**

In `backend/main.py`, add:

```python
from app.api.skills import router as skills_router
```

And:

```python
app.include_router(skills_router)
```

- [ ] **Step 3: Test API manually**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
CAPE_AGENT_RELOAD=1 python main.py &
sleep 2

# List skills (empty)
curl -s http://127.0.0.1:8001/api/skills | python -m json.tool

# Create a skill
curl -s -X POST http://127.0.0.1:8001/api/skills \
  -H "Content-Type: application/json" \
  -d '{"name":"test-skill","description":"A test","agent_type":"browser","content":"## Steps\n1. Do something","tags":["test"]}' | python -m json.tool

# List again
curl -s http://127.0.0.1:8001/api/skills | python -m json.tool

# Get detail
curl -s http://127.0.0.1:8001/api/skills/test-skill | python -m json.tool

# Delete
curl -s -X DELETE http://127.0.0.1:8001/api/skills/test-skill | python -m json.tool

kill %1
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/skills.py backend/main.py
git commit -m "feat(skills): add REST API endpoints for skill management"
```

---

### Task 9: Frontend Types and API Service

**Files:**
- Modify: `frontend/src/renderer/types/index.ts`
- Modify: `frontend/src/renderer/services/api.ts`

- [ ] **Step 1: Add skill types**

Append to `frontend/src/renderer/types/index.ts`:

```typescript
// --- Skills ---

export interface SkillMeta {
  name: string;
  description: string;
  agent_type: "browser" | "developer" | "document";
  version: number;
  enabled: boolean;
  created_by: "agent" | "user";
  created_at: string;
  updated_at: string;
  tags: string[];
}

export interface SkillDetail extends SkillMeta {
  content: string;
  raw: string;
  files: string[];
}

export interface SkillCreate {
  name: string;
  description: string;
  agent_type: "browser" | "developer" | "document";
  content: string;
  tags: string[];
}

export interface SkillUpdate {
  description?: string;
  content?: string;
  tags?: string[];
  enabled?: boolean;
}

export interface SkillStats {
  name: string;
  loads: number;
  patches: number;
  last_used: string | null;
}
```

- [ ] **Step 2: Add skill API functions**

Append to `frontend/src/renderer/services/api.ts`:

```typescript
// --- Skills ---

export async function fetchSkills(agentType?: string): Promise<SkillMeta[]> {
  await ensureApiUrl();
  const params = agentType ? `?agent_type=${agentType}` : "";
  const res = await fetch(`${BASE_URL}/api/skills${params}`);
  return res.json();
}

export async function fetchSkillDetail(name: string): Promise<SkillDetail> {
  await ensureApiUrl();
  const res = await fetch(`${BASE_URL}/api/skills/${name}`);
  if (!res.ok) throw new Error(`Skill '${name}' not found`);
  return res.json();
}

export async function createSkill(data: SkillCreate): Promise<SkillMeta> {
  await ensureApiUrl();
  const res = await fetch(`${BASE_URL}/api/skills`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to create skill");
  }
  return res.json();
}

export async function updateSkill(name: string, data: SkillUpdate): Promise<SkillMeta> {
  await ensureApiUrl();
  const res = await fetch(`${BASE_URL}/api/skills/${name}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to update skill");
  }
  return res.json();
}

export async function deleteSkill(name: string): Promise<void> {
  await ensureApiUrl();
  const res = await fetch(`${BASE_URL}/api/skills/${name}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete skill");
}

export async function fetchSkillStats(): Promise<SkillStats[]> {
  await ensureApiUrl();
  const res = await fetch(`${BASE_URL}/api/skills/stats`);
  return res.json();
}
```

Add skill type imports at the top of `api.ts`:

```typescript
import type { Conversation, Message, AppSettings, ChatRequest, SSEEvent, SkillMeta, SkillDetail, SkillCreate, SkillUpdate, SkillStats } from "../types";
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/renderer/types/index.ts frontend/src/renderer/services/api.ts
git commit -m "feat(skills): add frontend types and API service for skills"
```

---

### Task 10: Frontend Store Extension for Skills

**Files:**
- Modify: `frontend/src/renderer/stores/store.ts`

- [ ] **Step 1: Add skill state and actions to the store**

Add to the `AppState` interface (after the `taskStates` section):

```typescript
  // Skills
  skills: SkillMeta[];
  activeSkill: SkillDetail | null;
  skillStats: Record<string, SkillStats>;
  setSkills: (skills: SkillMeta[]) => void;
  setActiveSkill: (skill: SkillDetail | null) => void;
  setSkillStats: (stats: SkillStats[]) => void;
  updateSkillInList: (updated: SkillMeta) => void;
  removeSkillFromList: (name: string) => void;
```

Add to the `create<AppState>` body (after the task state implementations):

```typescript
  // Skills
  skills: [],
  activeSkill: null,
  skillStats: {},
  setSkills: (skills) => set({ skills }),
  setActiveSkill: (skill) => set({ activeSkill: skill }),
  setSkillStats: (stats) => {
    const map: Record<string, SkillStats> = {};
    for (const s of stats) map[s.name] = s;
    set({ skillStats: map });
  },
  updateSkillInList: (updated) =>
    set((s) => ({
      skills: s.skills.map((sk) => (sk.name === updated.name ? { ...sk, ...updated } : sk)),
    })),
  removeSkillFromList: (name) =>
    set((s) => ({
      skills: s.skills.filter((sk) => sk.name !== name),
    })),
```

Add the import for `SkillMeta`, `SkillDetail`, `SkillStats` in the store's import line.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/renderer/stores/store.ts
git commit -m "feat(skills): add skill state management to Zustand store"
```

---

### Task 11: Frontend Skills Pages

**Files:**
- Create: `frontend/src/renderer/components/skills/SkillList.tsx`
- Create: `frontend/src/renderer/components/skills/SkillDetailView.tsx`
- Create: `frontend/src/renderer/components/skills/SkillEditor.tsx`
- Create: `frontend/src/renderer/hooks/useSkills.ts`
- Modify: `frontend/src/renderer/App.tsx`
- Modify: `frontend/src/renderer/components/layout/Sidebar.tsx`

This is a large task. The full React component code is provided inline.

- [ ] **Step 1: Create useSkills hook**

```typescript
// frontend/src/renderer/hooks/useSkills.ts
import { useCallback, useEffect, useState } from "react";
import { useStore } from "../stores/store";
import * as api from "../services/api";
import type { SkillCreate, SkillUpdate } from "../types";

export function useSkills() {
  const skills = useStore((s) => s.skills);
  const setSkills = useStore((s) => s.setSkills);
  const setSkillStats = useStore((s) => s.setSkillStats);
  const updateSkillInList = useStore((s) => s.updateSkillInList);
  const removeSkillFromList = useStore((s) => s.removeSkillFromList);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async (agentType?: string) => {
    setLoading(true);
    try {
      const [list, stats] = await Promise.all([
        api.fetchSkills(agentType),
        api.fetchSkillStats(),
      ]);
      setSkills(list);
      setSkillStats(stats);
    } finally {
      setLoading(false);
    }
  }, [setSkills, setSkillStats]);

  const create = useCallback(async (data: SkillCreate) => {
    const created = await api.createSkill(data);
    await refresh();
    return created;
  }, [refresh]);

  const update = useCallback(async (name: string, data: SkillUpdate) => {
    const updated = await api.updateSkill(name, data);
    updateSkillInList(updated);
    return updated;
  }, [updateSkillInList]);

  const remove = useCallback(async (name: string) => {
    await api.deleteSkill(name);
    removeSkillFromList(name);
  }, [removeSkillFromList]);

  const toggleEnabled = useCallback(async (name: string, enabled: boolean) => {
    const updated = await api.updateSkill(name, { enabled });
    updateSkillInList(updated);
  }, [updateSkillInList]);

  return { skills, loading, refresh, create, update, remove, toggleEnabled };
}
```

- [ ] **Step 2: Create SkillList component**

```tsx
// frontend/src/renderer/components/skills/SkillList.tsx
import React, { useEffect, useState } from "react";
import { Plus, Globe, Code, FileText, ArrowLeft } from "lucide-react";
import { useSkills } from "../../hooks/useSkills";
import { useStore } from "../../stores/store";
import type { SkillMeta } from "../../types";

const AGENT_ICONS: Record<string, React.ReactNode> = {
  browser: <Globe size={14} />,
  developer: <Code size={14} />,
  document: <FileText size={14} />,
};

const AGENT_COLORS: Record<string, string> = {
  browser: "bg-blue-100 text-blue-700",
  developer: "bg-green-100 text-green-700",
  document: "bg-amber-100 text-amber-700",
};

interface Props {
  onSelect: (name: string) => void;
  onNew: () => void;
  onBack: () => void;
}

const SkillList: React.FC<Props> = ({ onSelect, onNew, onBack }) => {
  const { skills, loading, refresh, toggleEnabled } = useSkills();
  const skillStats = useStore((s) => s.skillStats);
  const [filter, setFilter] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    refresh(filter || undefined);
  }, [filter, refresh]);

  const filtered = skills.filter((s) => {
    if (search) {
      const q = search.toLowerCase();
      return (
        s.name.includes(q) ||
        s.description.toLowerCase().includes(q) ||
        s.tags.some((t) => t.includes(q))
      );
    }
    return true;
  });

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-4 border-b border-warm-200/40 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="p-1.5 rounded-lg text-navy-light hover:text-navy hover:bg-warm-200 transition-colors">
            <ArrowLeft size={16} />
          </button>
          <h1 className="text-lg font-bold text-navy">Skills</h1>
        </div>
        <button
          onClick={onNew}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-pastel-purple text-navy rounded-lg hover:bg-pastel-pink transition-colors"
        >
          <Plus size={14} /> New Skill
        </button>
      </div>

      <div className="px-6 py-3 flex items-center gap-2">
        {["All", "Browser", "Developer", "Document"].map((label) => {
          const value = label === "All" ? null : label.toLowerCase();
          const active = filter === value;
          return (
            <button
              key={label}
              onClick={() => setFilter(value)}
              className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
                active
                  ? "bg-navy text-white"
                  : "bg-warm-200/50 text-navy-light hover:bg-warm-200"
              }`}
            >
              {label}
            </button>
          );
        })}
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search..."
          className="ml-auto px-3 py-1 text-sm bg-warm-100 border border-warm-200/40 rounded-lg outline-none focus:border-navy/30 w-48"
        />
      </div>

      <div className="flex-1 overflow-y-auto px-6 pb-6 space-y-2">
        {loading && <div className="text-navy-light text-sm py-8 text-center">Loading...</div>}
        {!loading && filtered.length === 0 && (
          <div className="text-navy-light text-sm py-8 text-center">
            No skills yet. Create one or let agents learn from task execution.
          </div>
        )}
        {filtered.map((skill) => (
          <SkillCard
            key={skill.name}
            skill={skill}
            stats={skillStats[skill.name]}
            onClick={() => onSelect(skill.name)}
            onToggle={(enabled) => toggleEnabled(skill.name, enabled)}
          />
        ))}
      </div>
    </div>
  );
};

const SkillCard: React.FC<{
  skill: SkillMeta;
  stats?: { loads: number; patches: number };
  onClick: () => void;
  onToggle: (enabled: boolean) => void;
}> = ({ skill, stats, onClick, onToggle }) => (
  <div
    onClick={onClick}
    className="p-4 bg-white rounded-xl border border-warm-200/40 hover:border-navy/20 cursor-pointer transition-colors"
  >
    <div className="flex items-center justify-between mb-1">
      <div className="flex items-center gap-2">
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full ${AGENT_COLORS[skill.agent_type]}`}>
          {AGENT_ICONS[skill.agent_type]} {skill.agent_type}
        </span>
        <span className="font-semibold text-sm text-navy">{skill.name}</span>
        <span className="text-[11px] text-navy-light">v{skill.version}</span>
      </div>
      <button
        onClick={(e) => { e.stopPropagation(); onToggle(!skill.enabled); }}
        className={`text-[11px] px-2 py-0.5 rounded-full ${
          skill.enabled ? "bg-green-100 text-green-700" : "bg-warm-200 text-navy-light"
        }`}
      >
        {skill.enabled ? "enabled" : "disabled"}
      </button>
    </div>
    <p className="text-xs text-navy-light mb-2">{skill.description}</p>
    <div className="flex items-center gap-3 text-[11px] text-navy-light">
      {skill.tags.map((t) => (
        <span key={t} className="bg-warm-100 px-1.5 py-0.5 rounded">{t}</span>
      ))}
      {stats && <span className="ml-auto">loads: {stats.loads}</span>}
      <span className="text-navy-light/50">{skill.created_by}</span>
    </div>
  </div>
);

export default SkillList;
```

- [ ] **Step 3: Create SkillDetailView component**

```tsx
// frontend/src/renderer/components/skills/SkillDetailView.tsx
import React, { useEffect, useState } from "react";
import { ArrowLeft, Edit, Trash2 } from "lucide-react";
import * as api from "../../services/api";
import { useStore } from "../../stores/store";
import MarkdownContent from "../chat/MarkdownContent";
import type { SkillDetail } from "../../types";

interface Props {
  name: string;
  onBack: () => void;
  onEdit: (name: string) => void;
  onDeleted: () => void;
}

const SkillDetailView: React.FC<Props> = ({ name, onBack, onEdit, onDeleted }) => {
  const [skill, setSkill] = useState<SkillDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const skillStats = useStore((s) => s.skillStats);
  const stats = skillStats[name];

  useEffect(() => {
    setLoading(true);
    api.fetchSkillDetail(name).then(setSkill).finally(() => setLoading(false));
  }, [name]);

  const handleDelete = async () => {
    if (!confirm(`Delete skill "${name}"?`)) return;
    await api.deleteSkill(name);
    onDeleted();
  };

  if (loading) return <div className="p-6 text-navy-light">Loading...</div>;
  if (!skill) return <div className="p-6 text-navy-light">Skill not found.</div>;

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-4 border-b border-warm-200/40 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="p-1.5 rounded-lg text-navy-light hover:text-navy hover:bg-warm-200 transition-colors">
            <ArrowLeft size={16} />
          </button>
          <h1 className="text-lg font-bold text-navy">{skill.name}</h1>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => onEdit(name)}
            className="flex items-center gap-1 px-3 py-1.5 text-sm bg-warm-200/50 text-navy rounded-lg hover:bg-warm-200 transition-colors"
          >
            <Edit size={14} /> Edit
          </button>
          <button
            onClick={handleDelete}
            className="flex items-center gap-1 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 rounded-lg transition-colors"
          >
            <Trash2 size={14} /> Delete
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        <div className="flex flex-wrap items-center gap-3 mb-4 text-xs text-navy-light">
          <span className="bg-warm-100 px-2 py-0.5 rounded">{skill.agent_type}</span>
          <span>v{skill.version}</span>
          <span>by {skill.created_by}</span>
          {stats && <span>loads: {stats.loads}</span>}
          {skill.tags.map((t) => (
            <span key={t} className="bg-warm-200/50 px-1.5 py-0.5 rounded">{t}</span>
          ))}
        </div>
        <div className="prose prose-sm max-w-none">
          <MarkdownContent content={skill.content} />
        </div>
        {skill.files.length > 0 && (
          <div className="mt-6">
            <h3 className="text-sm font-semibold text-navy mb-2">Supporting Files</h3>
            <ul className="text-xs text-navy-light space-y-1">
              {skill.files.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
};

export default SkillDetailView;
```

- [ ] **Step 4: Create SkillEditor component**

```tsx
// frontend/src/renderer/components/skills/SkillEditor.tsx
import React, { useEffect, useState } from "react";
import { ArrowLeft, Save } from "lucide-react";
import * as api from "../../services/api";
import type { SkillDetail } from "../../types";

interface Props {
  name?: string; // undefined = create mode
  onBack: () => void;
  onSaved: (name: string) => void;
}

const SkillEditor: React.FC<Props> = ({ name: editName, onBack, onSaved }) => {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [agentType, setAgentType] = useState<"browser" | "developer" | "document">("browser");
  const [content, setContent] = useState("");
  const [tags, setTags] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const isEdit = !!editName;

  useEffect(() => {
    if (editName) {
      api.fetchSkillDetail(editName).then((skill) => {
        setName(skill.name);
        setDescription(skill.description);
        setAgentType(skill.agent_type);
        setContent(skill.content);
        setTags(skill.tags.join(", "));
      });
    }
  }, [editName]);

  const handleSave = async () => {
    setError("");
    setSaving(true);
    try {
      if (isEdit) {
        await api.updateSkill(editName!, {
          description,
          content,
          tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
        });
        onSaved(editName!);
      } else {
        const created = await api.createSkill({
          name,
          description,
          agent_type: agentType,
          content,
          tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
        });
        onSaved(created.name);
      }
    } catch (e: any) {
      setError(e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-4 border-b border-warm-200/40 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="p-1.5 rounded-lg text-navy-light hover:text-navy hover:bg-warm-200 transition-colors">
            <ArrowLeft size={16} />
          </button>
          <h1 className="text-lg font-bold text-navy">{isEdit ? "Edit Skill" : "New Skill"}</h1>
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-pastel-purple text-navy rounded-lg hover:bg-pastel-pink transition-colors disabled:opacity-50"
        >
          <Save size={14} /> {saving ? "Saving..." : "Save"}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {error && <div className="text-red-600 text-sm bg-red-50 px-3 py-2 rounded-lg">{error}</div>}

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-navy-light mb-1">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isEdit}
              placeholder="my-skill-name"
              className="w-full px-3 py-2 text-sm bg-warm-100 border border-warm-200/40 rounded-lg outline-none focus:border-navy/30 disabled:opacity-50"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-navy-light mb-1">Agent Type</label>
            <select
              value={agentType}
              onChange={(e) => setAgentType(e.target.value as any)}
              disabled={isEdit}
              className="w-full px-3 py-2 text-sm bg-warm-100 border border-warm-200/40 rounded-lg outline-none focus:border-navy/30 disabled:opacity-50"
            >
              <option value="browser">Browser</option>
              <option value="developer">Developer</option>
              <option value="document">Document</option>
            </select>
          </div>
        </div>

        <div>
          <label className="block text-xs font-medium text-navy-light mb-1">Description</label>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="One-line description of what this skill does"
            className="w-full px-3 py-2 text-sm bg-warm-100 border border-warm-200/40 rounded-lg outline-none focus:border-navy/30"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-navy-light mb-1">Tags (comma separated)</label>
          <input
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="search, academic, google"
            className="w-full px-3 py-2 text-sm bg-warm-100 border border-warm-200/40 rounded-lg outline-none focus:border-navy/30"
          />
        </div>

        <div className="flex-1">
          <label className="block text-xs font-medium text-navy-light mb-1">Content (Markdown)</label>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder={"## Trigger Conditions\nWhen to use this skill.\n\n## Steps\n1. First step\n2. Second step\n\n## Pitfalls\n- Known issue\n\n## Verification\n- How to confirm success"}
            className="w-full h-96 px-3 py-2 text-sm font-mono bg-warm-100 border border-warm-200/40 rounded-lg outline-none focus:border-navy/30 resize-y"
          />
        </div>
      </div>
    </div>
  );
};

export default SkillEditor;
```

- [ ] **Step 5: Add skills navigation to Sidebar and App**

Add a "Skills" button to the Sidebar. In `frontend/src/renderer/components/layout/Sidebar.tsx`, add to the bottom section (before the closing `</div>` of the outer container), alongside the settings button:

```tsx
import { Zap } from "lucide-react";
// ... inside the settings row at the bottom of sidebar:
<button
  onClick={() => useStore.getState().setShowSkills(true)}
  className="p-1.5 rounded-lg text-navy-light hover:text-navy hover:bg-warm-100 transition-colors"
  title="Skills"
>
  <Zap size={16} />
</button>
```

Add `showSkills` / `setShowSkills` to the store interface and implementation:

```typescript
// In AppState interface:
showSkills: boolean;
setShowSkills: (show: boolean) => void;
skillsView: { page: "list" | "detail" | "edit" | "new"; name?: string };
setSkillsView: (view: { page: "list" | "detail" | "edit" | "new"; name?: string }) => void;

// In create body:
showSkills: false,
setShowSkills: (show) => set({ showSkills: show, skillsView: { page: "list" } }),
skillsView: { page: "list" },
setSkillsView: (view) => set({ skillsView: view }),
```

In `App.tsx`, add skills panel rendering:

```tsx
import SkillList from "./components/skills/SkillList";
import SkillDetailView from "./components/skills/SkillDetailView";
import SkillEditor from "./components/skills/SkillEditor";

// Inside the App component, after <SettingsModal />:
const showSkills = useStore((s) => s.showSkills);
const skillsView = useStore((s) => s.skillsView);
const setShowSkills = useStore((s) => s.setShowSkills);
const setSkillsView = useStore((s) => s.setSkillsView);

// Render skills panel as overlay when showSkills is true:
{showSkills && (
  <div className="fixed inset-0 z-50 bg-warm-100">
    {skillsView.page === "list" && (
      <SkillList
        onSelect={(name) => setSkillsView({ page: "detail", name })}
        onNew={() => setSkillsView({ page: "new" })}
        onBack={() => setShowSkills(false)}
      />
    )}
    {skillsView.page === "detail" && skillsView.name && (
      <SkillDetailView
        name={skillsView.name}
        onBack={() => setSkillsView({ page: "list" })}
        onEdit={(name) => setSkillsView({ page: "edit", name })}
        onDeleted={() => setSkillsView({ page: "list" })}
      />
    )}
    {skillsView.page === "edit" && skillsView.name && (
      <SkillEditor
        name={skillsView.name}
        onBack={() => setSkillsView({ page: "detail", name: skillsView.name })}
        onSaved={(name) => setSkillsView({ page: "detail", name })}
      />
    )}
    {skillsView.page === "new" && (
      <SkillEditor
        onBack={() => setSkillsView({ page: "list" })}
        onSaved={(name) => setSkillsView({ page: "detail", name })}
      />
    )}
  </div>
)}
```

- [ ] **Step 6: Add SSE event handling for skill events**

In `store.ts`, inside `handleSSEEvent`, add cases for new skill events:

```typescript
case "skill_loaded":
case "insight_marked":
case "skill_evolved":
  // These are informational — append to agent logs
  set((s) => {
    const state = s.taskStates[conversationId] || defaultTaskState();
    return {
      taskStates: {
        ...s.taskStates,
        [conversationId]: {
          ...state,
          agentLogs: [
            ...state.agentLogs,
            {
              agentId: String(event.data.agent || "system"),
              agentName: String(event.data.agent || "Skill System"),
              processTaskId: "",
              status: "done" as const,
              inputMessage: event.step,
              outputMessage: JSON.stringify(event.data),
              timestamp: new Date().toISOString(),
            },
          ],
        },
      },
    };
  });
  break;
```

- [ ] **Step 7: Build and test frontend**

```bash
cd /Users/didi/Documents/opensource/cape-agent/frontend
npm run build
```

Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/renderer/components/skills/ frontend/src/renderer/hooks/useSkills.ts frontend/src/renderer/App.tsx frontend/src/renderer/components/layout/Sidebar.tsx frontend/src/renderer/stores/store.ts
git commit -m "feat(skills): add complete frontend skills management UI"
```

---

### Task 12: End-to-End Smoke Test

- [ ] **Step 1: Start backend and create a skill via API**

```bash
cd /Users/didi/Documents/opensource/cape-agent/backend
python main.py &
sleep 3

curl -s -X POST http://127.0.0.1:8001/api/skills \
  -H "Content-Type: application/json" \
  -d '{
    "name": "google-scholar-search",
    "description": "Optimized Google Scholar paper search workflow",
    "agent_type": "browser",
    "content": "## Trigger Conditions\nWhen searching for academic papers.\n\n## Steps\n1. Use search_google with site:scholar.google.com\n2. If blocked, switch to DuckDuckGo\n\n## Pitfalls\n- Rate limit after 3 rapid requests\n\n## Verification\n- Got title + abstract + link",
    "tags": ["search", "academic"]
  }' | python -m json.tool
```

Expected: 201 response with skill metadata.

- [ ] **Step 2: Verify skill file exists on disk**

```bash
cat ~/.cape-agent/skills/browser/google-scholar-search/SKILL.md
```

Expected: YAML frontmatter + markdown body.

- [ ] **Step 3: Verify snapshot was invalidated**

```bash
ls -la ~/.cape-agent/skills/.snapshot.json 2>/dev/null || echo "No snapshot (correct — invalidated on create)"
```

- [ ] **Step 4: List skills (triggers snapshot rebuild)**

```bash
curl -s http://127.0.0.1:8001/api/skills | python -m json.tool
```

Expected: Array with one skill, snapshot rebuilt.

- [ ] **Step 5: Start the full app and test frontend**

```bash
cd /Users/didi/Documents/opensource/cape-agent/frontend
npm run dev
```

Open the app, click the Skills (lightning bolt) icon in the sidebar. Verify:
- Skills list shows the created skill
- Click to see detail view
- Edit and save works
- New skill creation works
- Delete works

- [ ] **Step 6: Clean up test skill**

```bash
curl -s -X DELETE http://127.0.0.1:8001/api/skills/google-scholar-search
kill %1
```

- [ ] **Step 7: Commit any final adjustments**

```bash
git add -A
git commit -m "test: verify skill evolution system end-to-end"
```
