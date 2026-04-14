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
