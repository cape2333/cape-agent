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
