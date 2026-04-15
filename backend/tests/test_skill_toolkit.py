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
