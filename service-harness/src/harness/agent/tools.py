"""Agent tools for observing and acting on the system."""

from typing import Optional, Dict, Any, List, Callable
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import json
import os

from sqlalchemy.orm import Session

from harness.config import get_settings
from harness.grafana import PrometheusClient, LokiClient
from harness.models import Ticket, TicketEvent, TicketEventType, TicketStatus, TicketPriority, TicketSourceType


class AgentToolkit:
    """Collection of tools available to the agent.

    Tools are organized into two categories:
    - Observe: Query metrics, logs, read files, search code
    - Act: Edit files, run commands, create tickets, add notes

    Each tool returns a result dict with 'success' and either 'data' or 'error'.
    """

    def __init__(
        self,
        db: Session,
        prometheus_client: Optional[PrometheusClient] = None,
        loki_client: Optional[LokiClient] = None,
        workspace_path: Optional[str] = None,
    ):
        """Initialize the toolkit.

        Args:
            db: Database session for ticket operations
            prometheus_client: Optional Prometheus client
            loki_client: Optional Loki client
            workspace_path: Path to the service workspace (for file operations)
        """
        self.db = db
        self._prometheus = prometheus_client
        self._loki = loki_client
        self.workspace_path = Path(workspace_path) if workspace_path else Path.cwd()

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get Claude-compatible tool definitions.

        Returns:
            List of tool definitions for Claude's tool_use feature
        """
        return [
            # === OBSERVE TOOLS ===
            {
                "name": "query_metrics",
                "description": "Query Prometheus metrics using PromQL. Use this to check current system state, error rates, latencies, etc.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "PromQL query string (e.g., 'rate(http_requests_total[5m])')"
                        },
                        "range_minutes": {
                            "type": "integer",
                            "description": "Optional: query range in minutes for time-series data. If not provided, returns instant query."
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "query_logs",
                "description": "Query Loki logs using LogQL. Use this to search for error messages, debug output, etc.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "LogQL query string (e.g., '{app=\"myservice\"} |= \"error\"')"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of log entries to return (default: 100)"
                        },
                        "range_minutes": {
                            "type": "integer",
                            "description": "How far back to search in minutes (default: 60)"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "read_file",
                "description": "Read the contents of a file in the workspace. Use this to examine code, configuration, etc.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path to the file within the workspace"
                        },
                        "start_line": {
                            "type": "integer",
                            "description": "Optional: starting line number (1-indexed)"
                        },
                        "end_line": {
                            "type": "integer",
                            "description": "Optional: ending line number (inclusive)"
                        }
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "list_files",
                "description": "List files in a directory within the workspace.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path to the directory (default: workspace root)"
                        },
                        "pattern": {
                            "type": "string",
                            "description": "Optional glob pattern to filter files (e.g., '*.py')"
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "search_code",
                "description": "Search for a pattern in files using grep. Use this to find relevant code.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Search pattern (supports regex)"
                        },
                        "file_pattern": {
                            "type": "string",
                            "description": "Optional glob pattern for files to search (e.g., '*.py')"
                        },
                        "context_lines": {
                            "type": "integer",
                            "description": "Number of context lines around matches (default: 2)"
                        }
                    },
                    "required": ["pattern"]
                }
            },
            # === ACT TOOLS ===
            {
                "name": "edit_file",
                "description": "Edit a file in the workspace. Creates the file if it doesn't exist. Changes should be atomic and complete.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path to the file"
                        },
                        "content": {
                            "type": "string",
                            "description": "New content for the file (replaces entire file)"
                        },
                        "description": {
                            "type": "string",
                            "description": "Brief description of the change (for commit message)"
                        }
                    },
                    "required": ["path", "content", "description"]
                }
            },
            {
                "name": "run_command",
                "description": "Run a shell command in the workspace. Use for running tests, builds, etc. CAUTION: Be careful with commands that modify state.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to run"
                        },
                        "timeout_seconds": {
                            "type": "integer",
                            "description": "Command timeout in seconds (default: 60, max: 300)"
                        }
                    },
                    "required": ["command"]
                }
            },
            {
                "name": "add_ticket_note",
                "description": "Add a note to the current ticket. Use this to document findings, progress, or decisions.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ticket_id": {
                            "type": "integer",
                            "description": "Ticket ID to add note to"
                        },
                        "note": {
                            "type": "string",
                            "description": "Note content"
                        }
                    },
                    "required": ["ticket_id", "note"]
                }
            },
            {
                "name": "create_ticket",
                "description": "Create a new ticket for follow-up work discovered during investigation.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "objective": {
                            "type": "string",
                            "description": "What needs to be achieved"
                        },
                        "success_criteria": {
                            "type": "string",
                            "description": "How to verify the objective is met"
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["low", "medium", "high", "critical"],
                            "description": "Ticket priority (default: medium)"
                        },
                        "context": {
                            "type": "object",
                            "description": "Optional additional context"
                        }
                    },
                    "required": ["objective"]
                }
            },
            {
                "name": "update_ticket_status",
                "description": "Update the status of a ticket.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ticket_id": {
                            "type": "integer",
                            "description": "Ticket ID to update"
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed", "failed", "blocked"],
                            "description": "New status"
                        },
                        "reason": {
                            "type": "string",
                            "description": "Reason for the status change"
                        }
                    },
                    "required": ["ticket_id", "status"]
                }
            },
        ]

    def execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool by name.

        Args:
            tool_name: Name of the tool to execute
            tool_input: Input parameters for the tool

        Returns:
            Result dict with 'success' and 'data' or 'error'
        """
        tool_methods = {
            "query_metrics": self._query_metrics,
            "query_logs": self._query_logs,
            "read_file": self._read_file,
            "list_files": self._list_files,
            "search_code": self._search_code,
            "edit_file": self._edit_file,
            "run_command": self._run_command,
            "add_ticket_note": self._add_ticket_note,
            "create_ticket": self._create_ticket,
            "update_ticket_status": self._update_ticket_status,
        }

        if tool_name not in tool_methods:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        try:
            return tool_methods[tool_name](tool_input)
        except Exception as e:
            return {"success": False, "error": str(e)}

    # === OBSERVE TOOLS ===

    def _query_metrics(self, input: Dict[str, Any]) -> Dict[str, Any]:
        """Query Prometheus metrics."""
        if not self._prometheus:
            self._prometheus = PrometheusClient()

        query = input["query"]
        range_minutes = input.get("range_minutes")

        try:
            if range_minutes:
                end = datetime.utcnow()
                start = end - timedelta(minutes=range_minutes)
                result = self._prometheus.query_range(query, start, end)
            else:
                result = self._prometheus.query(query)

            return {"success": True, "data": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _query_logs(self, input: Dict[str, Any]) -> Dict[str, Any]:
        """Query Loki logs."""
        if not self._loki:
            self._loki = LokiClient()

        query = input["query"]
        limit = input.get("limit", 100)
        range_minutes = input.get("range_minutes", 60)

        try:
            end = datetime.utcnow()
            start = end - timedelta(minutes=range_minutes)
            result = self._loki.query(query, limit=limit, start=start, end=end)
            return {"success": True, "data": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _read_file(self, input: Dict[str, Any]) -> Dict[str, Any]:
        """Read a file from the workspace."""
        path = self.workspace_path / input["path"]

        # Security: ensure path is within workspace
        try:
            path = path.resolve()
            if not str(path).startswith(str(self.workspace_path.resolve())):
                return {"success": False, "error": "Path is outside workspace"}
        except Exception:
            return {"success": False, "error": "Invalid path"}

        if not path.exists():
            return {"success": False, "error": f"File not found: {input['path']}"}

        if not path.is_file():
            return {"success": False, "error": f"Not a file: {input['path']}"}

        try:
            content = path.read_text()
            lines = content.splitlines()

            start_line = input.get("start_line", 1) - 1
            end_line = input.get("end_line", len(lines))

            selected_lines = lines[start_line:end_line]
            return {
                "success": True,
                "data": {
                    "path": input["path"],
                    "content": "\n".join(selected_lines),
                    "total_lines": len(lines),
                    "start_line": start_line + 1,
                    "end_line": min(end_line, len(lines)),
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _list_files(self, input: Dict[str, Any]) -> Dict[str, Any]:
        """List files in a directory."""
        rel_path = input.get("path", "")
        pattern = input.get("pattern", "*")

        path = self.workspace_path / rel_path

        # Security: ensure path is within workspace
        try:
            path = path.resolve()
            if not str(path).startswith(str(self.workspace_path.resolve())):
                return {"success": False, "error": "Path is outside workspace"}
        except Exception:
            return {"success": False, "error": "Invalid path"}

        if not path.exists():
            return {"success": False, "error": f"Directory not found: {rel_path}"}

        if not path.is_dir():
            return {"success": False, "error": f"Not a directory: {rel_path}"}

        try:
            files = []
            workspace_resolved = self.workspace_path.resolve()
            for p in path.glob(pattern):
                rel = p.relative_to(workspace_resolved)
                files.append({
                    "path": str(rel),
                    "is_dir": p.is_dir(),
                    "size": p.stat().st_size if p.is_file() else None,
                })
            return {"success": True, "data": {"files": files}}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _search_code(self, input: Dict[str, Any]) -> Dict[str, Any]:
        """Search for a pattern in files using grep."""
        pattern = input["pattern"]
        file_pattern = input.get("file_pattern", "*")
        context_lines = input.get("context_lines", 2)

        try:
            # Use grep for searching
            cmd = ["grep", "-rn", f"-C{context_lines}", pattern]
            if file_pattern != "*":
                cmd.extend(["--include", file_pattern])
            cmd.append(str(self.workspace_path))

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            matches = []
            for line in result.stdout.splitlines()[:100]:  # Limit results
                matches.append(line)

            return {
                "success": True,
                "data": {
                    "matches": matches,
                    "count": len(matches),
                    "truncated": len(result.stdout.splitlines()) > 100,
                }
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Search timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # === ACT TOOLS ===

    def _edit_file(self, input: Dict[str, Any]) -> Dict[str, Any]:
        """Edit a file in the workspace."""
        path = self.workspace_path / input["path"]
        content = input["content"]
        description = input["description"]

        # Security: ensure path is within workspace
        try:
            # Resolve parent to check, path may not exist yet
            parent = path.parent.resolve()
            if not str(parent).startswith(str(self.workspace_path.resolve())):
                return {"success": False, "error": "Path is outside workspace"}
        except Exception:
            return {"success": False, "error": "Invalid path"}

        try:
            # Create parent directories if needed
            path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            path.write_text(content)

            return {
                "success": True,
                "data": {
                    "path": input["path"],
                    "description": description,
                    "bytes_written": len(content),
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _run_command(self, input: Dict[str, Any]) -> Dict[str, Any]:
        """Run a shell command."""
        command = input["command"]
        timeout = min(input.get("timeout_seconds", 60), 300)  # Max 5 minutes

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.workspace_path),
            )

            return {
                "success": True,
                "data": {
                    "command": command,
                    "return_code": result.returncode,
                    "stdout": result.stdout[:10000],  # Limit output
                    "stderr": result.stderr[:10000],
                }
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Command timed out after {timeout}s"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _add_ticket_note(self, input: Dict[str, Any]) -> Dict[str, Any]:
        """Add a note to a ticket."""
        ticket_id = input["ticket_id"]
        note = input["note"]

        ticket = self.db.get(Ticket, ticket_id)
        if not ticket:
            return {"success": False, "error": f"Ticket {ticket_id} not found"}

        event = TicketEvent(
            ticket_id=ticket_id,
            event_type=TicketEventType.NOTE_ADDED,
            data={"note": note, "source": "agent"},
        )
        self.db.add(event)
        self.db.commit()

        return {
            "success": True,
            "data": {"ticket_id": ticket_id, "event_id": event.id}
        }

    def _create_ticket(self, input: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new ticket."""
        priority_map = {
            "low": TicketPriority.LOW,
            "medium": TicketPriority.MEDIUM,
            "high": TicketPriority.HIGH,
            "critical": TicketPriority.CRITICAL,
        }

        ticket = Ticket(
            objective=input["objective"],
            success_criteria=input.get("success_criteria"),
            context=input.get("context", {}),
            priority=priority_map.get(input.get("priority", "medium"), TicketPriority.MEDIUM),
            source_type=TicketSourceType.HUMAN,  # Agent-created tickets are treated as human-initiated
        )
        self.db.add(ticket)
        self.db.flush()

        event = TicketEvent(
            ticket_id=ticket.id,
            event_type=TicketEventType.CREATED,
            data={"source": "agent", "created_by": "agent"},
        )
        self.db.add(event)
        self.db.commit()

        return {
            "success": True,
            "data": {"ticket_id": ticket.id, "objective": ticket.objective}
        }

    def _update_ticket_status(self, input: Dict[str, Any]) -> Dict[str, Any]:
        """Update ticket status."""
        ticket_id = input["ticket_id"]
        new_status = input["status"]
        reason = input.get("reason", "")

        status_map = {
            "pending": TicketStatus.PENDING,
            "in_progress": TicketStatus.IN_PROGRESS,
            "completed": TicketStatus.COMPLETED,
            "failed": TicketStatus.FAILED,
            "blocked": TicketStatus.BLOCKED,
        }

        if new_status not in status_map:
            return {"success": False, "error": f"Invalid status: {new_status}"}

        ticket = self.db.get(Ticket, ticket_id)
        if not ticket:
            return {"success": False, "error": f"Ticket {ticket_id} not found"}

        old_status = ticket.status.value
        ticket.status = status_map[new_status]

        if new_status in ["completed", "failed"]:
            ticket.resolved_at = datetime.utcnow()

        event = TicketEvent(
            ticket_id=ticket_id,
            event_type=TicketEventType.STATUS_CHANGED,
            data={
                "old_status": old_status,
                "new_status": new_status,
                "reason": reason,
                "source": "agent",
            },
        )
        self.db.add(event)
        self.db.commit()

        return {
            "success": True,
            "data": {
                "ticket_id": ticket_id,
                "old_status": old_status,
                "new_status": new_status,
            }
        }
