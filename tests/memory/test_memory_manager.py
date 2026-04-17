"""Tests for MemoryManager."""

from pathlib import Path

import pytest

from reachy_mini_conversation_app.memory.memory_manager import (
    MemoryManager,
    _estimate_tokens,
)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Return a temporary data directory."""
    return tmp_path / "data"


@pytest.fixture
def manager(data_dir: Path) -> MemoryManager:
    """Create a fresh MemoryManager in a temp directory."""
    return MemoryManager(data_dir)


# ------------------------------------------------------------------
# Initialization
# ------------------------------------------------------------------


class TestInit:
    """Verify directory creation and initial state."""

    def test_creates_directories(self, manager: MemoryManager, data_dir: Path) -> None:
        """Create memory and logs directories on init."""
        assert (data_dir / "memory").is_dir()
        assert (data_dir / "memory" / "logs").is_dir()

    def test_active_memory_empty_on_fresh_start(self, manager: MemoryManager) -> None:
        """Return empty memory block when no facts saved."""
        assert manager.get_memory_block() == ""

    def test_initial_session_log_created(self, manager: MemoryManager, data_dir: Path) -> None:
        """Create one session log file on init."""
        log_files = list((data_dir / "memory" / "logs").glob("*.log"))
        assert len(log_files) == 1
        content = log_files[0].read_text()
        assert content.startswith("--- session")

    def test_new_session_creates_new_log(self, manager: MemoryManager, data_dir: Path) -> None:
        """Create a second log file on new_session()."""
        manager.new_session()
        log_files = list((data_dir / "memory" / "logs").glob("*.log"))
        assert len(log_files) == 2


# ------------------------------------------------------------------
# Tier 1: Conversation logging (per-session plain text)
# ------------------------------------------------------------------


class TestConversationLogging:
    """Verify per-session plain-text conversation logging."""

    def test_log_turn_creates_entry(self, manager: MemoryManager) -> None:
        """Append a turn to the session log."""
        manager.log_turn("user", "Hello there!")
        content = manager._session_log_path.read_text()
        assert "user: Hello there!" in content

    def test_log_turn_appends(self, manager: MemoryManager) -> None:
        """Append multiple turns sequentially."""
        manager.log_turn("user", "First")
        manager.log_turn("assistant", "Second")
        content = manager._session_log_path.read_text()
        assert "user: First" in content
        assert "assistant: Second" in content

    def test_log_turn_has_timestamp(self, manager: MemoryManager) -> None:
        """Prefix each log line with HH:MM:SS."""
        manager.log_turn("user", "Hello")
        lines = manager._session_log_path.read_text().splitlines()
        # Find the line with the log entry (skip header)
        log_lines = [ln for ln in lines if "user:" in ln]
        assert len(log_lines) == 1
        # Should start with HH:MM:SS
        assert log_lines[0][2] == ":" and log_lines[0][5] == ":"

    def test_log_turn_ignores_empty(self, manager: MemoryManager) -> None:
        """Skip empty or whitespace-only turns."""
        manager.log_turn("user", "")
        manager.log_turn("user", "   ")
        content = manager._session_log_path.read_text()
        assert "user:" not in content

    def test_log_tool_call(self, manager: MemoryManager) -> None:
        """Log a tool call with args and result."""
        manager.log_tool_call("dance", args={"name": "happy"}, result={"status": "queued"})
        content = manager._session_log_path.read_text()
        assert 'tool: dance({"name": "happy"})' in content
        assert '{"status": "queued"}' in content

    def test_new_session_writes_to_new_file(self, manager: MemoryManager) -> None:
        """Rotate to a new log file on new_session()."""
        manager.log_turn("user", "Before")
        old_path = manager._session_log_path
        manager.new_session()
        manager.log_turn("user", "After")
        new_path = manager._session_log_path

        assert old_path != new_path
        assert "Before" in old_path.read_text()
        assert "After" in new_path.read_text()
        assert "After" not in old_path.read_text()

    def test_filename_collision_handling(self, manager: MemoryManager, data_dir: Path) -> None:
        """Generate unique filenames for rapid session creation."""
        # Create multiple sessions rapidly — should get _2, _3 suffixes
        paths = [manager._session_log_path]
        for _ in range(3):
            manager.new_session()
            paths.append(manager._session_log_path)
        # All paths should be unique
        assert len(set(paths)) == len(paths)


# ------------------------------------------------------------------
# Tier 2: Active memory
# ------------------------------------------------------------------


class TestActiveMemory:
    """Verify active memory save and retrieval."""

    def test_save_memory(self, manager: MemoryManager) -> None:
        """Save a fact and return status."""
        result = manager.save_memory("User's name is Alice")
        assert result["status"] == "saved"
        assert "Alice" in result["fact"]

    def test_save_memory_appears_in_block(self, manager: MemoryManager) -> None:
        """Include saved facts in the memory block."""
        manager.save_memory("User's name is Alice")
        block = manager.get_memory_block()
        assert "Alice" in block
        assert "## MEMORY" in block

    def test_save_memory_has_log_ref(self, manager: MemoryManager) -> None:
        """Attach session log filename reference to saved facts."""
        manager.save_memory("User's name is Alice")
        block = manager.get_memory_block()
        assert ".log)" in block

    def test_save_memory_format(self, manager: MemoryManager) -> None:
        """Store facts as 'text (filename.log)' entries."""
        manager.save_memory("User's name is Alice")
        lines = manager._read_active_lines()
        # Format: "fact text (YYYY-MM-DD_HH-MM.log)"
        assert len(lines) == 1
        assert lines[0].startswith("User's name is Alice (")
        assert lines[0].endswith(".log)")

    def test_save_memory_rejects_empty(self, manager: MemoryManager) -> None:
        """Reject empty fact strings."""
        result = manager.save_memory("")
        assert "error" in result

    def test_save_memory_rejects_whitespace(self, manager: MemoryManager) -> None:
        """Reject whitespace-only fact strings."""
        result = manager.save_memory("   ")
        assert "error" in result

    def test_multiple_saves(self, manager: MemoryManager) -> None:
        """Accumulate multiple facts in the memory block."""
        manager.save_memory("Fact one")
        manager.save_memory("Fact two")
        block = manager.get_memory_block()
        assert "Fact one" in block
        assert "Fact two" in block


# ------------------------------------------------------------------
# Recall (read session logs)
# ------------------------------------------------------------------


class TestRecall:
    """Verify session log recall."""

    def test_recall_returns_session_log(self, manager: MemoryManager) -> None:
        """Read back a session log by filename."""
        manager.log_turn("user", "Hello, my name is Rémi")
        manager.log_turn("assistant", "Nice to meet you!")
        log_name = manager._session_log_path.name
        result = manager.recall_memory(log_name)
        assert "content" in result
        assert "Rémi" in result["content"]
        assert "Nice to meet you" in result["content"]

    def test_recall_file_not_found(self, manager: MemoryManager) -> None:
        """Return error and available files for missing log."""
        result = manager.recall_memory("nonexistent.log")
        assert "error" in result
        assert "available_logs" in result

    def test_recall_empty_lists_files(self, manager: MemoryManager) -> None:
        """List available log files when called with empty string."""
        result = manager.recall_memory("")
        assert "available_logs" in result
        assert len(result["available_logs"]) >= 1  # at least the init session log

    def test_recall_via_save_memory_ref(self, manager: MemoryManager) -> None:
        """End-to-end: save a memory, extract its ref, recall the session log."""
        manager.log_turn("user", "I love playing chess")
        manager.save_memory("User loves chess")

        # Extract the log ref from the active memory entry
        lines = manager._read_active_lines()
        entry = [ln for ln in lines if "chess" in ln][0]
        # Format: "User loves chess (2026-03-26_16-28.log)"
        log_ref = entry.split("(")[-1].rstrip(")")

        result = manager.recall_memory(log_ref)
        assert "content" in result
        assert "chess" in result["content"]


# ------------------------------------------------------------------
# Prompt injection
# ------------------------------------------------------------------


class TestPromptInjection:
    """Verify memory block formatting for prompt injection."""

    def test_empty_memory_returns_empty_string(self, manager: MemoryManager) -> None:
        """Return empty string when no facts are saved."""
        assert manager.get_memory_block() == ""

    def test_memory_block_format(self, manager: MemoryManager) -> None:
        """Format memory block with header and tool references."""
        manager.save_memory("User's name is Alice")
        block = manager.get_memory_block()
        assert block.startswith("\n\n## MEMORY\n")
        assert "save_memory" in block
        assert "recall_memory" in block
        assert "Alice" in block


# ------------------------------------------------------------------
# Token estimation
# ------------------------------------------------------------------


class TestTokenEstimation:
    """Verify character-based token estimation."""

    def test_estimate_tokens_short(self) -> None:
        """Estimate at least 1 token for short text."""
        assert _estimate_tokens("hello") >= 1

    def test_estimate_tokens_long(self) -> None:
        """Estimate ~1000 tokens for 3500 characters."""
        text = "a" * 3500  # 3500 chars ≈ 1000 tokens
        tokens = _estimate_tokens(text)
        assert 900 <= tokens <= 1100

    def test_estimate_tokens_empty(self) -> None:
        """Return minimum 1 for empty string."""
        assert _estimate_tokens("") == 1  # minimum 1
