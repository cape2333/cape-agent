"""Tests for build_conversation_context()."""

import os
import tempfile

from app.models.enums import Status
from app.services.task_lock import TaskLock
from app.services.agent_service import build_conversation_context


class TestBuildConversationContext:
    """Tests for build_conversation_context()."""

    def test_empty_history_returns_empty_string(self):
        task_lock = TaskLock(id="conv-1", status=Status.classifying)
        result = build_conversation_context(task_lock)
        assert result == ""

    def test_single_round_formats_correctly(self):
        task_lock = TaskLock(id="conv-1", status=Status.classifying)
        task_lock.conversation_history.append({
            "task_content": "Research React frameworks",
            "task_result": "Found React, Vue, and Angular as top 3.",
            "working_directory": "/tmp/test-workspace",
        })
        result = build_conversation_context(task_lock)
        assert "=== CONVERSATION HISTORY ===" in result
        assert "Round 1" in result
        assert "Research React frameworks" in result
        assert "Found React, Vue, and Angular as top 3." in result

    def test_multiple_rounds_all_included(self):
        task_lock = TaskLock(id="conv-1", status=Status.classifying)
        task_lock.conversation_history.append({
            "task_content": "Research React",
            "task_result": "React is a UI library.",
            "working_directory": "/tmp/ws1",
        })
        task_lock.conversation_history.append({
            "task_content": "Write comparison doc",
            "task_result": "Document saved to /tmp/ws2/comparison.md",
            "working_directory": "/tmp/ws2",
        })
        result = build_conversation_context(task_lock)
        assert "Round 1" in result
        assert "Round 2" in result
        assert "Research React" in result
        assert "Write comparison doc" in result

    def test_generated_files_listed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "output.md")
            with open(test_file, "w") as f:
                f.write("test")

            task_lock = TaskLock(id="conv-1", status=Status.classifying)
            task_lock.conversation_history.append({
                "task_content": "Generate report",
                "task_result": "Report generated.",
                "working_directory": tmpdir,
            })
            result = build_conversation_context(task_lock)
            assert "Generated Files:" in result
            assert "output.md" in result

    def test_missing_working_directory_skipped(self):
        task_lock = TaskLock(id="conv-1", status=Status.classifying)
        task_lock.conversation_history.append({
            "task_content": "Some task",
            "task_result": "Done.",
            "working_directory": "/nonexistent/path/abc123",
        })
        result = build_conversation_context(task_lock)
        assert "=== CONVERSATION HISTORY ===" in result
        assert "Generated Files:" not in result

    def test_empty_task_result_omitted(self):
        task_lock = TaskLock(id="conv-1", status=Status.classifying)
        task_lock.conversation_history.append({
            "task_content": "Some task",
            "task_result": "",
            "working_directory": "",
        })
        result = build_conversation_context(task_lock)
        assert "Result:" not in result
