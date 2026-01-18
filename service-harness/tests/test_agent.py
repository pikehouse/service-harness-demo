"""Tests for the agent module."""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from sqlalchemy.orm import Session

from harness.agent.tools import AgentToolkit
from harness.agent.runner import AgentRunner
from harness.models import (
    Ticket, TicketEvent, TicketStatus, TicketPriority,
    TicketSourceType, TicketEventType, TicketDependency,
)


class TestAgentToolkit:
    """Tests for AgentToolkit."""

    def test_get_tool_definitions(self, db_session: Session):
        """Test that tool definitions are valid."""
        toolkit = AgentToolkit(db=db_session)
        tools = toolkit.get_tool_definitions()

        assert len(tools) == 10  # 5 observe + 5 act tools

        # Check all tools have required fields
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"

        # Check specific tools exist
        tool_names = [t["name"] for t in tools]
        assert "query_metrics" in tool_names
        assert "query_logs" in tool_names
        assert "read_file" in tool_names
        assert "list_files" in tool_names
        assert "search_code" in tool_names
        assert "edit_file" in tool_names
        assert "run_command" in tool_names
        assert "add_ticket_note" in tool_names
        assert "create_ticket" in tool_names
        assert "update_ticket_status" in tool_names

    def test_execute_unknown_tool(self, db_session: Session):
        """Test executing an unknown tool returns error."""
        toolkit = AgentToolkit(db=db_session)
        result = toolkit.execute_tool("unknown_tool", {})

        assert result["success"] is False
        assert "Unknown tool" in result["error"]


class TestReadFileTool:
    """Tests for the read_file tool."""

    def test_read_file_success(self, db_session: Session):
        """Test reading a file successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test file
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("line 1\nline 2\nline 3")

            toolkit = AgentToolkit(db=db_session, workspace_path=tmpdir)
            result = toolkit.execute_tool("read_file", {"path": "test.txt"})

            assert result["success"] is True
            assert "line 1" in result["data"]["content"]
            assert result["data"]["total_lines"] == 3
            assert result["data"]["path"] == "test.txt"

    def test_read_file_with_line_range(self, db_session: Session):
        """Test reading specific lines from a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("line 1\nline 2\nline 3\nline 4\nline 5")

            toolkit = AgentToolkit(db=db_session, workspace_path=tmpdir)
            result = toolkit.execute_tool("read_file", {
                "path": "test.txt",
                "start_line": 2,
                "end_line": 4,
            })

            assert result["success"] is True
            assert "line 2" in result["data"]["content"]
            assert "line 3" in result["data"]["content"]
            assert "line 4" in result["data"]["content"]
            assert "line 1" not in result["data"]["content"]
            assert "line 5" not in result["data"]["content"]

    def test_read_file_not_found(self, db_session: Session):
        """Test reading a nonexistent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            toolkit = AgentToolkit(db=db_session, workspace_path=tmpdir)
            result = toolkit.execute_tool("read_file", {"path": "nonexistent.txt"})

            assert result["success"] is False
            assert "not found" in result["error"]

    def test_read_file_path_traversal_blocked(self, db_session: Session):
        """Test that path traversal attempts are blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            toolkit = AgentToolkit(db=db_session, workspace_path=tmpdir)
            result = toolkit.execute_tool("read_file", {"path": "../../../etc/passwd"})

            assert result["success"] is False
            assert "outside workspace" in result["error"]


class TestListFilesTool:
    """Tests for the list_files tool."""

    def test_list_files_success(self, db_session: Session):
        """Test listing files in a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "file1.py").write_text("# python")
            (Path(tmpdir) / "file2.txt").write_text("text")
            (Path(tmpdir) / "subdir").mkdir()

            toolkit = AgentToolkit(db=db_session, workspace_path=tmpdir)
            result = toolkit.execute_tool("list_files", {})

            assert result["success"] is True, f"Failed: {result.get('error')}"
            files = result["data"]["files"]
            paths = [f["path"] for f in files]
            assert "file1.py" in paths
            assert "file2.txt" in paths
            assert "subdir" in paths

    def test_list_files_with_pattern(self, db_session: Session):
        """Test listing files with a glob pattern."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "file1.py").write_text("")
            (Path(tmpdir) / "file2.py").write_text("")
            (Path(tmpdir) / "file3.txt").write_text("")

            toolkit = AgentToolkit(db=db_session, workspace_path=tmpdir)
            result = toolkit.execute_tool("list_files", {"pattern": "*.py"})

            assert result["success"] is True, f"Failed: {result.get('error')}"
            files = result["data"]["files"]
            paths = [f["path"] for f in files]
            assert "file1.py" in paths
            assert "file2.py" in paths
            assert "file3.txt" not in paths

    def test_list_files_path_traversal_blocked(self, db_session: Session):
        """Test that path traversal is blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            toolkit = AgentToolkit(db=db_session, workspace_path=tmpdir)
            result = toolkit.execute_tool("list_files", {"path": "../.."})

            assert result["success"] is False
            assert "outside workspace" in result["error"]


class TestEditFileTool:
    """Tests for the edit_file tool."""

    def test_edit_file_create(self, db_session: Session):
        """Test creating a new file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            toolkit = AgentToolkit(db=db_session, workspace_path=tmpdir)
            result = toolkit.execute_tool("edit_file", {
                "path": "new_file.py",
                "content": "print('hello')",
                "description": "Create greeting file",
            })

            assert result["success"] is True
            assert result["data"]["path"] == "new_file.py"

            # Verify file was created
            created = Path(tmpdir) / "new_file.py"
            assert created.exists()
            assert created.read_text() == "print('hello')"

    def test_edit_file_update(self, db_session: Session):
        """Test updating an existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create existing file
            test_file = Path(tmpdir) / "existing.py"
            test_file.write_text("old content")

            toolkit = AgentToolkit(db=db_session, workspace_path=tmpdir)
            result = toolkit.execute_tool("edit_file", {
                "path": "existing.py",
                "content": "new content",
                "description": "Update file",
            })

            assert result["success"] is True
            assert test_file.read_text() == "new content"

    def test_edit_file_creates_directories(self, db_session: Session):
        """Test that missing directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            toolkit = AgentToolkit(db=db_session, workspace_path=tmpdir)
            result = toolkit.execute_tool("edit_file", {
                "path": "new/nested/dir/file.py",
                "content": "nested content",
                "description": "Create nested file",
            })

            assert result["success"] is True

            created = Path(tmpdir) / "new" / "nested" / "dir" / "file.py"
            assert created.exists()
            assert created.read_text() == "nested content"

    def test_edit_file_path_traversal_blocked(self, db_session: Session):
        """Test that path traversal is blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            toolkit = AgentToolkit(db=db_session, workspace_path=tmpdir)
            result = toolkit.execute_tool("edit_file", {
                "path": "../outside.py",
                "content": "malicious",
                "description": "Try to escape",
            })

            assert result["success"] is False
            assert "outside workspace" in result["error"]


class TestRunCommandTool:
    """Tests for the run_command tool."""

    def test_run_command_success(self, db_session: Session):
        """Test running a simple command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            toolkit = AgentToolkit(db=db_session, workspace_path=tmpdir)
            result = toolkit.execute_tool("run_command", {
                "command": "echo hello",
            })

            assert result["success"] is True
            assert result["data"]["return_code"] == 0
            assert "hello" in result["data"]["stdout"]

    def test_run_command_failure(self, db_session: Session):
        """Test running a failing command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            toolkit = AgentToolkit(db=db_session, workspace_path=tmpdir)
            result = toolkit.execute_tool("run_command", {
                "command": "exit 1",
            })

            assert result["success"] is True  # Tool succeeded, command failed
            assert result["data"]["return_code"] == 1

    def test_run_command_timeout(self, db_session: Session):
        """Test command timeout."""
        with tempfile.TemporaryDirectory() as tmpdir:
            toolkit = AgentToolkit(db=db_session, workspace_path=tmpdir)
            result = toolkit.execute_tool("run_command", {
                "command": "sleep 10",
                "timeout_seconds": 1,
            })

            assert result["success"] is False
            assert "timed out" in result["error"]


class TestTicketTools:
    """Tests for ticket-related tools."""

    def test_add_ticket_note(self, db_session: Session):
        """Test adding a note to a ticket."""
        # Create a ticket
        ticket = Ticket(
            objective="Test ticket",
            source_type=TicketSourceType.HUMAN,
        )
        db_session.add(ticket)
        db_session.commit()

        toolkit = AgentToolkit(db=db_session)
        result = toolkit.execute_tool("add_ticket_note", {
            "ticket_id": ticket.id,
            "note": "Investigation found the root cause",
        })

        assert result["success"] is True
        assert result["data"]["ticket_id"] == ticket.id

        # Check event was created
        events = list(db_session.query(TicketEvent).filter(
            TicketEvent.ticket_id == ticket.id,
            TicketEvent.event_type == TicketEventType.NOTE_ADDED,
        ).all())
        assert len(events) == 1
        assert events[0].data["note"] == "Investigation found the root cause"

    def test_add_ticket_note_not_found(self, db_session: Session):
        """Test adding a note to a nonexistent ticket."""
        toolkit = AgentToolkit(db=db_session)
        result = toolkit.execute_tool("add_ticket_note", {
            "ticket_id": 99999,
            "note": "This should fail",
        })

        assert result["success"] is False
        assert "not found" in result["error"]

    def test_create_ticket(self, db_session: Session):
        """Test creating a new ticket."""
        toolkit = AgentToolkit(db=db_session)
        result = toolkit.execute_tool("create_ticket", {
            "objective": "Fix the memory leak",
            "success_criteria": "Memory usage stays below 500MB",
            "priority": "high",
        })

        assert result["success"] is True
        ticket_id = result["data"]["ticket_id"]

        # Verify ticket was created
        ticket = db_session.get(Ticket, ticket_id)
        assert ticket is not None
        assert ticket.objective == "Fix the memory leak"
        assert ticket.success_criteria == "Memory usage stays below 500MB"
        assert ticket.priority == TicketPriority.HIGH

    def test_update_ticket_status(self, db_session: Session):
        """Test updating ticket status."""
        ticket = Ticket(
            objective="Test ticket",
            source_type=TicketSourceType.HUMAN,
            status=TicketStatus.IN_PROGRESS,
        )
        db_session.add(ticket)
        db_session.commit()

        toolkit = AgentToolkit(db=db_session)
        result = toolkit.execute_tool("update_ticket_status", {
            "ticket_id": ticket.id,
            "status": "completed",
            "reason": "Fixed the issue",
        })

        assert result["success"] is True
        assert result["data"]["old_status"] == "in_progress"
        assert result["data"]["new_status"] == "completed"

        # Verify status changed
        db_session.refresh(ticket)
        assert ticket.status == TicketStatus.COMPLETED
        assert ticket.resolved_at is not None

    def test_update_ticket_status_invalid(self, db_session: Session):
        """Test updating with invalid status."""
        ticket = Ticket(
            objective="Test ticket",
            source_type=TicketSourceType.HUMAN,
        )
        db_session.add(ticket)
        db_session.commit()

        toolkit = AgentToolkit(db=db_session)
        result = toolkit.execute_tool("update_ticket_status", {
            "ticket_id": ticket.id,
            "status": "invalid_status",
        })

        assert result["success"] is False
        assert "Invalid status" in result["error"]


class TestQueryMetricsTool:
    """Tests for the query_metrics tool."""

    def test_query_metrics_instant(self, db_session: Session):
        """Test instant metric query."""
        mock_prometheus = Mock()
        mock_prometheus.query.return_value = {"result": [{"value": [123, "42"]}]}

        toolkit = AgentToolkit(
            db=db_session,
            prometheus_client=mock_prometheus,
        )
        result = toolkit.execute_tool("query_metrics", {
            "query": "up",
        })

        assert result["success"] is True
        mock_prometheus.query.assert_called_once_with("up")

    def test_query_metrics_range(self, db_session: Session):
        """Test range metric query."""
        mock_prometheus = Mock()
        mock_prometheus.query_range.return_value = {"result": []}

        toolkit = AgentToolkit(
            db=db_session,
            prometheus_client=mock_prometheus,
        )
        result = toolkit.execute_tool("query_metrics", {
            "query": "rate(requests[5m])",
            "range_minutes": 30,
        })

        assert result["success"] is True
        mock_prometheus.query_range.assert_called_once()


class TestQueryLogsTool:
    """Tests for the query_logs tool."""

    def test_query_logs(self, db_session: Session):
        """Test log query."""
        mock_loki = Mock()
        mock_loki.query.return_value = {"result": []}

        toolkit = AgentToolkit(
            db=db_session,
            loki_client=mock_loki,
        )
        result = toolkit.execute_tool("query_logs", {
            "query": '{app="test"} |= "error"',
            "limit": 50,
        })

        assert result["success"] is True
        mock_loki.query.assert_called_once()


class TestAgentRunner:
    """Tests for AgentRunner."""

    def test_get_ready_tickets_no_dependencies(self, db_session: Session):
        """Test getting ready tickets without dependencies."""
        # Create some tickets
        t1 = Ticket(objective="Task 1", source_type=TicketSourceType.HUMAN, status=TicketStatus.PENDING)
        t2 = Ticket(objective="Task 2", source_type=TicketSourceType.HUMAN, status=TicketStatus.PENDING)
        t3 = Ticket(objective="Task 3", source_type=TicketSourceType.HUMAN, status=TicketStatus.IN_PROGRESS)
        db_session.add_all([t1, t2, t3])
        db_session.commit()

        runner = AgentRunner(
            session_factory=lambda: db_session,
            api_key="test-key",
        )
        ready = runner.get_ready_tickets(db_session)

        assert len(ready) == 2
        assert t3 not in ready  # Not pending

    def test_get_ready_tickets_with_dependencies(self, db_session: Session):
        """Test ready tickets with dependencies."""
        t1 = Ticket(objective="Prereq", source_type=TicketSourceType.HUMAN, status=TicketStatus.PENDING)
        t2 = Ticket(objective="Depends on t1", source_type=TicketSourceType.HUMAN, status=TicketStatus.PENDING)
        db_session.add_all([t1, t2])
        db_session.commit()

        # t2 depends on t1
        dep = TicketDependency(ticket_id=t2.id, depends_on_id=t1.id)
        db_session.add(dep)
        db_session.commit()

        runner = AgentRunner(
            session_factory=lambda: db_session,
            api_key="test-key",
        )
        ready = runner.get_ready_tickets(db_session)

        assert len(ready) == 1
        assert ready[0].id == t1.id  # Only t1 is ready

    def test_get_ready_tickets_dependency_completed(self, db_session: Session):
        """Test that ticket becomes ready when dependency completes."""
        t1 = Ticket(objective="Prereq", source_type=TicketSourceType.HUMAN, status=TicketStatus.COMPLETED)
        t2 = Ticket(objective="Depends on t1", source_type=TicketSourceType.HUMAN, status=TicketStatus.PENDING)
        db_session.add_all([t1, t2])
        db_session.commit()

        dep = TicketDependency(ticket_id=t2.id, depends_on_id=t1.id)
        db_session.add(dep)
        db_session.commit()

        runner = AgentRunner(
            session_factory=lambda: db_session,
            api_key="test-key",
        )
        ready = runner.get_ready_tickets(db_session)

        assert len(ready) == 1
        assert ready[0].id == t2.id  # t2 is now ready

    def test_get_ready_tickets_priority_order(self, db_session: Session):
        """Test that ready tickets are sorted by priority."""
        t_low = Ticket(
            objective="Low priority",
            source_type=TicketSourceType.HUMAN,
            status=TicketStatus.PENDING,
            priority=TicketPriority.LOW,
        )
        t_critical = Ticket(
            objective="Critical",
            source_type=TicketSourceType.HUMAN,
            status=TicketStatus.PENDING,
            priority=TicketPriority.CRITICAL,
        )
        t_medium = Ticket(
            objective="Medium",
            source_type=TicketSourceType.HUMAN,
            status=TicketStatus.PENDING,
            priority=TicketPriority.MEDIUM,
        )
        db_session.add_all([t_low, t_critical, t_medium])
        db_session.commit()

        runner = AgentRunner(
            session_factory=lambda: db_session,
            api_key="test-key",
        )
        ready = runner.get_ready_tickets(db_session)

        assert len(ready) == 3
        assert ready[0].priority == TicketPriority.CRITICAL
        assert ready[1].priority == TicketPriority.MEDIUM
        assert ready[2].priority == TicketPriority.LOW

    def test_build_initial_messages(self, db_session: Session):
        """Test building initial messages for Claude."""
        ticket = Ticket(
            objective="Fix the bug",
            success_criteria="Tests pass",
            source_type=TicketSourceType.SLO_VIOLATION,
            priority=TicketPriority.HIGH,
            context={"error": "NullPointerException"},
        )
        db_session.add(ticket)
        db_session.commit()

        runner = AgentRunner(
            session_factory=lambda: db_session,
            api_key="test-key",
        )
        messages = runner._build_initial_messages(ticket)

        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        content = messages[0]["content"]
        assert "Fix the bug" in content
        assert "Tests pass" in content
        assert "high" in content
        assert "slo_violation" in content
        assert "NullPointerException" in content

    def test_run_once_no_work(self, db_session: Session):
        """Test run_once when no tickets are ready."""
        runner = AgentRunner(
            session_factory=lambda: db_session,
            api_key="test-key",
        )
        result = runner.run_once()

        assert result["status"] == "no_work"

    @patch("harness.agent.runner.Anthropic")
    def test_work_ticket_completes(self, mock_anthropic_class, db_session: Session):
        """Test working a ticket to completion."""
        # Create mock response
        mock_client = Mock()
        mock_anthropic_class.return_value = mock_client

        mock_text_block = Mock()
        mock_text_block.type = "text"
        mock_text_block.text = "I have completed the investigation and fixed the issue."

        mock_response = Mock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [mock_text_block]

        mock_client.messages.create.return_value = mock_response

        # Create ticket
        ticket = Ticket(
            objective="Test ticket",
            source_type=TicketSourceType.HUMAN,
            status=TicketStatus.PENDING,
        )
        db_session.add(ticket)
        db_session.commit()

        runner = AgentRunner(
            session_factory=lambda: db_session,
            api_key="test-key",
        )
        trajectory = runner.work_ticket(ticket, db_session)

        assert trajectory["final_status"] == "completed"
        assert trajectory["turns_used"] == 1

        # Verify ticket status changed
        db_session.refresh(ticket)
        assert ticket.status == TicketStatus.COMPLETED

    @patch("harness.agent.runner.Anthropic")
    def test_work_ticket_with_tool_use(self, mock_anthropic_class, db_session: Session):
        """Test working a ticket with tool use."""
        mock_client = Mock()
        mock_anthropic_class.return_value = mock_client

        # First response: tool use
        mock_tool_block = Mock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.id = "tool_123"
        mock_tool_block.name = "read_file"
        mock_tool_block.input = {"path": "test.txt"}

        mock_response1 = Mock()
        mock_response1.stop_reason = "tool_use"
        mock_response1.content = [mock_tool_block]

        # Second response: completion
        mock_text_block = Mock()
        mock_text_block.type = "text"
        mock_text_block.text = "I found the issue and it's now fixed."

        mock_response2 = Mock()
        mock_response2.stop_reason = "end_turn"
        mock_response2.content = [mock_text_block]

        mock_client.messages.create.side_effect = [mock_response1, mock_response2]

        # Create ticket
        ticket = Ticket(
            objective="Test ticket",
            source_type=TicketSourceType.HUMAN,
            status=TicketStatus.PENDING,
        )
        db_session.add(ticket)
        db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test file for read_file tool
            (Path(tmpdir) / "test.txt").write_text("file content")

            runner = AgentRunner(
                session_factory=lambda: db_session,
                api_key="test-key",
                workspace_path=tmpdir,
            )
            trajectory = runner.work_ticket(ticket, db_session)

        assert trajectory["final_status"] == "completed"
        assert trajectory["turns_used"] == 2
        assert len(trajectory["steps"]) == 2

        # Check first step had tool call
        assert "tool_calls" in trajectory["steps"][0]
        assert trajectory["steps"][0]["tool_calls"][0]["tool"] == "read_file"

    @patch("harness.agent.runner.Anthropic")
    def test_work_ticket_blocked(self, mock_anthropic_class, db_session: Session):
        """Test ticket getting blocked."""
        mock_client = Mock()
        mock_anthropic_class.return_value = mock_client

        mock_text_block = Mock()
        mock_text_block.type = "text"
        mock_text_block.text = "I am blocked because I need help from a human."

        mock_response = Mock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [mock_text_block]

        mock_client.messages.create.return_value = mock_response

        ticket = Ticket(
            objective="Test ticket",
            source_type=TicketSourceType.HUMAN,
            status=TicketStatus.PENDING,
        )
        db_session.add(ticket)
        db_session.commit()

        runner = AgentRunner(
            session_factory=lambda: db_session,
            api_key="test-key",
        )
        trajectory = runner.work_ticket(ticket, db_session)

        assert trajectory["final_status"] == "blocked"

        db_session.refresh(ticket)
        assert ticket.status == TicketStatus.BLOCKED

    @patch("harness.agent.runner.Anthropic")
    def test_work_ticket_max_turns(self, mock_anthropic_class, db_session: Session):
        """Test ticket failing due to max turns."""
        mock_client = Mock()
        mock_anthropic_class.return_value = mock_client

        # Always return tool use (never completes)
        mock_tool_block = Mock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.id = "tool_123"
        mock_tool_block.name = "run_command"
        mock_tool_block.input = {"command": "echo hello"}

        mock_response = Mock()
        mock_response.stop_reason = "tool_use"
        mock_response.content = [mock_tool_block]

        mock_client.messages.create.return_value = mock_response

        ticket = Ticket(
            objective="Test ticket",
            source_type=TicketSourceType.HUMAN,
            status=TicketStatus.PENDING,
        )
        db_session.add(ticket)
        db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            runner = AgentRunner(
                session_factory=lambda: db_session,
                api_key="test-key",
                max_turns=3,
                workspace_path=tmpdir,
            )
            trajectory = runner.work_ticket(ticket, db_session)

        assert trajectory["final_status"] == "failed"
        assert trajectory["turns_used"] == 3

        db_session.refresh(ticket)
        assert ticket.status == TicketStatus.FAILED

    def test_runner_requires_api_key(self):
        """Test that runner requires an API key."""
        with patch("harness.agent.runner.get_settings") as mock_settings:
            mock_settings.return_value.anthropic_api_key = ""

            with pytest.raises(ValueError, match="API key is required"):
                AgentRunner()
