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


class TestSkillLoggerConcurrency:
    def test_concurrent_log_event_preserves_all_entries(self, logger, tmp_path):
        """Multiple threads calling log_event must not lose or interleave lines."""
        import threading
        N_THREADS = 8
        N_PER_THREAD = 25
        def worker(tid):
            for i in range(N_PER_THREAD):
                logger.log_event(
                    "skill_loaded", f"s-{tid}-{i}", "browser", f"conv-{tid}"
                )
        threads = [threading.Thread(target=worker, args=(t,)) for t in range(N_THREADS)]
        for t in threads: t.start()
        for t in threads: t.join()
        events_file = next((tmp_path / ".log").rglob("events.jsonl"))
        lines = [l for l in events_file.read_text().splitlines() if l.strip()]
        assert len(lines) == N_THREADS * N_PER_THREAD
        for line in lines:
            json.loads(line)  # every line parses (no interleaving)

    def test_concurrent_write_insight_preserves_all(self, logger):
        import threading
        N = 50
        def worker(i):
            logger.write_insight("browser", f"sum-{i}", "", "conv-x")
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert len(logger.read_pending_insights("conv-x")) == N

    def test_concurrent_stats_update_does_not_lose(self, logger):
        import threading
        N = 40
        def worker():
            logger.log_event("skill_loaded", "shared", "browser", "c")
        threads = [threading.Thread(target=worker) for _ in range(N)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert logger.get_stats()["shared"]["loads"] == N

    def test_clear_insights_survives_concurrent_writer(self, logger):
        """clear_insights reading, filtering, and rewriting under one lock
        must not drop insights appended by a concurrent write_insight."""
        import threading
        for i in range(20):
            logger.write_insight("browser", f"pre-{i}", "", "conv-keep")
        for i in range(10):
            logger.write_insight("browser", f"drop-{i}", "", "conv-drop")

        stop = threading.Event()
        def appender():
            i = 0
            while not stop.is_set():
                logger.write_insight("browser", f"live-{i}", "", "conv-keep")
                i += 1
        t = threading.Thread(target=appender); t.start()
        try:
            for _ in range(20):
                logger.clear_insights("conv-drop")
        finally:
            stop.set(); t.join()

        assert len(logger.read_pending_insights("conv-drop")) == 0
        kept = logger.read_pending_insights("conv-keep")
        assert len(kept) >= 20
        assert all(k["summary"].startswith(("pre-", "live-")) for k in kept)
