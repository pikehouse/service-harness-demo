"""Tests for the tickets API."""

import pytest
from fastapi.testclient import TestClient


class TestTicketsAPI:
    """Tests for the /api/tickets endpoints."""

    def test_health_check(self, client: TestClient):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_create_ticket(self, client: TestClient):
        """Test creating a ticket."""
        response = client.post(
            "/api/tickets",
            json={
                "objective": "Fix the bug in login",
                "success_criteria": "Users can log in successfully",
                "priority": "high",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] is not None
        assert data["objective"] == "Fix the bug in login"
        assert data["status"] == "pending"
        assert data["priority"] == "high"
        assert data["source_type"] == "human"
        assert len(data["events"]) == 1  # Created event
        assert data["events"][0]["event_type"] == "created"

    def test_create_ticket_minimal(self, client: TestClient):
        """Test creating a ticket with minimal data."""
        response = client.post(
            "/api/tickets",
            json={"objective": "Simple task"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["objective"] == "Simple task"
        assert data["status"] == "pending"
        assert data["priority"] == "medium"  # Default

    def test_create_ticket_with_context(self, client: TestClient):
        """Test creating a ticket with context."""
        response = client.post(
            "/api/tickets",
            json={
                "objective": "Debug error",
                "context": {"error_code": 500, "endpoint": "/api/users"},
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["context"]["error_code"] == 500

    def test_list_tickets_empty(self, client: TestClient):
        """Test listing tickets when none exist."""
        response = client.get("/api/tickets")
        assert response.status_code == 200
        data = response.json()
        assert data["tickets"] == []
        assert data["total"] == 0

    def test_list_tickets(self, client: TestClient):
        """Test listing tickets."""
        # Create some tickets
        client.post("/api/tickets", json={"objective": "Task 1"})
        client.post("/api/tickets", json={"objective": "Task 2"})
        client.post("/api/tickets", json={"objective": "Task 3"})

        response = client.get("/api/tickets")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["tickets"]) == 3

    def test_list_tickets_filter_by_status(self, client: TestClient):
        """Test filtering tickets by status."""
        # Create tickets with different statuses
        r1 = client.post("/api/tickets", json={"objective": "Pending"})
        r2 = client.post("/api/tickets", json={"objective": "In progress"})
        ticket2_id = r2.json()["id"]

        # Update second ticket to in_progress
        client.patch(f"/api/tickets/{ticket2_id}", json={"status": "in_progress"})

        # Filter by pending
        response = client.get("/api/tickets?status=pending")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["tickets"][0]["objective"] == "Pending"

        # Filter by in_progress
        response = client.get("/api/tickets?status=in_progress")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["tickets"][0]["objective"] == "In progress"

    def test_get_ticket(self, client: TestClient):
        """Test getting a ticket by ID."""
        # Create ticket
        create_resp = client.post(
            "/api/tickets",
            json={"objective": "Get me"},
        )
        ticket_id = create_resp.json()["id"]

        # Get ticket
        response = client.get(f"/api/tickets/{ticket_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == ticket_id
        assert data["objective"] == "Get me"
        assert "events" in data
        assert "dependencies" in data
        assert "is_ready" in data

    def test_get_ticket_not_found(self, client: TestClient):
        """Test getting a non-existent ticket."""
        response = client.get("/api/tickets/9999")
        assert response.status_code == 404

    def test_update_ticket_status(self, client: TestClient):
        """Test updating ticket status."""
        # Create ticket
        create_resp = client.post("/api/tickets", json={"objective": "Update me"})
        ticket_id = create_resp.json()["id"]

        # Update status
        response = client.patch(
            f"/api/tickets/{ticket_id}",
            json={"status": "in_progress"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "in_progress"

        # Check event was created
        assert len(data["events"]) == 2
        status_event = [e for e in data["events"] if e["event_type"] == "status_changed"][0]
        assert status_event["data"]["old_status"] == "pending"
        assert status_event["data"]["new_status"] == "in_progress"

    def test_update_ticket_priority(self, client: TestClient):
        """Test updating ticket priority."""
        create_resp = client.post("/api/tickets", json={"objective": "Prioritize me"})
        ticket_id = create_resp.json()["id"]

        response = client.patch(
            f"/api/tickets/{ticket_id}",
            json={"priority": "critical"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["priority"] == "critical"

        # Check event was created
        priority_event = [e for e in data["events"] if e["event_type"] == "priority_changed"][0]
        assert priority_event["data"]["old_priority"] == "medium"
        assert priority_event["data"]["new_priority"] == "critical"


class TestTicketEvents:
    """Tests for ticket events endpoints."""

    def test_list_ticket_events(self, client: TestClient):
        """Test listing ticket events."""
        # Create ticket
        create_resp = client.post("/api/tickets", json={"objective": "Events test"})
        ticket_id = create_resp.json()["id"]

        response = client.get(f"/api/tickets/{ticket_id}/events")
        assert response.status_code == 200
        events = response.json()
        assert len(events) == 1  # Created event
        assert events[0]["event_type"] == "created"

    def test_create_ticket_event(self, client: TestClient):
        """Test adding an event to a ticket."""
        create_resp = client.post("/api/tickets", json={"objective": "Add events"})
        ticket_id = create_resp.json()["id"]

        response = client.post(
            f"/api/tickets/{ticket_id}/events",
            json={
                "event_type": "note_added",
                "data": {"note": "Working on this now"},
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["event_type"] == "note_added"
        assert data["data"]["note"] == "Working on this now"

    def test_create_agent_action_event(self, client: TestClient):
        """Test adding an agent action event."""
        create_resp = client.post("/api/tickets", json={"objective": "Agent test"})
        ticket_id = create_resp.json()["id"]

        response = client.post(
            f"/api/tickets/{ticket_id}/events",
            json={
                "event_type": "agent_action",
                "data": {
                    "action": "edit_file",
                    "file": "src/main.py",
                    "changes": "Fixed null pointer",
                },
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["event_type"] == "agent_action"


class TestTicketDependencies:
    """Tests for ticket dependency endpoints."""

    def test_add_dependency(self, client: TestClient):
        """Test adding a dependency to a ticket."""
        # Create two tickets
        r1 = client.post("/api/tickets", json={"objective": "First task"})
        r2 = client.post("/api/tickets", json={"objective": "Depends on first"})
        ticket1_id = r1.json()["id"]
        ticket2_id = r2.json()["id"]

        # Add dependency
        response = client.post(
            f"/api/tickets/{ticket2_id}/dependencies",
            json={"depends_on_id": ticket1_id},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["ticket_id"] == ticket2_id
        assert data["depends_on_id"] == ticket1_id

    def test_list_dependencies(self, client: TestClient):
        """Test listing ticket dependencies."""
        r1 = client.post("/api/tickets", json={"objective": "First"})
        r2 = client.post("/api/tickets", json={"objective": "Second"})
        ticket1_id = r1.json()["id"]
        ticket2_id = r2.json()["id"]

        client.post(
            f"/api/tickets/{ticket2_id}/dependencies",
            json={"depends_on_id": ticket1_id},
        )

        response = client.get(f"/api/tickets/{ticket2_id}/dependencies")
        assert response.status_code == 200
        deps = response.json()
        assert len(deps) == 1
        assert deps[0]["depends_on_id"] == ticket1_id

    def test_remove_dependency(self, client: TestClient):
        """Test removing a dependency."""
        r1 = client.post("/api/tickets", json={"objective": "First"})
        r2 = client.post("/api/tickets", json={"objective": "Second"})
        ticket1_id = r1.json()["id"]
        ticket2_id = r2.json()["id"]

        client.post(
            f"/api/tickets/{ticket2_id}/dependencies",
            json={"depends_on_id": ticket1_id},
        )

        # Remove dependency
        response = client.delete(f"/api/tickets/{ticket2_id}/dependencies/{ticket1_id}")
        assert response.status_code == 204

        # Verify removed
        deps_response = client.get(f"/api/tickets/{ticket2_id}/dependencies")
        assert len(deps_response.json()) == 0

    def test_self_dependency_not_allowed(self, client: TestClient):
        """Test that a ticket cannot depend on itself."""
        r1 = client.post("/api/tickets", json={"objective": "Self ref"})
        ticket_id = r1.json()["id"]

        response = client.post(
            f"/api/tickets/{ticket_id}/dependencies",
            json={"depends_on_id": ticket_id},
        )
        assert response.status_code == 400
        assert "cannot depend on itself" in response.json()["detail"]

    def test_duplicate_dependency_not_allowed(self, client: TestClient):
        """Test that duplicate dependencies are rejected."""
        r1 = client.post("/api/tickets", json={"objective": "First"})
        r2 = client.post("/api/tickets", json={"objective": "Second"})
        ticket1_id = r1.json()["id"]
        ticket2_id = r2.json()["id"]

        # Add dependency
        client.post(
            f"/api/tickets/{ticket2_id}/dependencies",
            json={"depends_on_id": ticket1_id},
        )

        # Try to add same dependency again
        response = client.post(
            f"/api/tickets/{ticket2_id}/dependencies",
            json={"depends_on_id": ticket1_id},
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    def test_dependency_affects_ready_status(self, client: TestClient):
        """Test that dependencies affect ready status."""
        r1 = client.post("/api/tickets", json={"objective": "First"})
        r2 = client.post("/api/tickets", json={"objective": "Second"})
        ticket1_id = r1.json()["id"]
        ticket2_id = r2.json()["id"]

        # Before adding dependency, ticket2 should be ready
        ticket2 = client.get(f"/api/tickets/{ticket2_id}").json()
        assert ticket2["is_ready"] is True

        # Add dependency
        client.post(
            f"/api/tickets/{ticket2_id}/dependencies",
            json={"depends_on_id": ticket1_id},
        )

        # Now ticket2 should not be ready (dependency is pending)
        ticket2 = client.get(f"/api/tickets/{ticket2_id}").json()
        assert ticket2["is_ready"] is False

        # Complete ticket1
        client.patch(f"/api/tickets/{ticket1_id}", json={"status": "completed"})

        # Now ticket2 should be ready
        ticket2 = client.get(f"/api/tickets/{ticket2_id}").json()
        assert ticket2["is_ready"] is True


class TestReadyTickets:
    """Tests for the /api/tickets/ready endpoint."""

    def test_ready_tickets_empty(self, client: TestClient):
        """Test ready tickets when none exist."""
        response = client.get("/api/tickets/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["tickets"] == []
        assert data["total"] == 0

    def test_ready_tickets_no_dependencies(self, client: TestClient):
        """Test ready tickets with no dependencies are included."""
        client.post("/api/tickets", json={"objective": "Ready ticket"})

        response = client.get("/api/tickets/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

    def test_ready_tickets_excludes_in_progress(self, client: TestClient):
        """Test that in_progress tickets are not ready."""
        r1 = client.post("/api/tickets", json={"objective": "In progress"})
        ticket_id = r1.json()["id"]
        client.patch(f"/api/tickets/{ticket_id}", json={"status": "in_progress"})

        response = client.get("/api/tickets/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0

    def test_ready_tickets_with_completed_dependencies(self, client: TestClient):
        """Test that tickets with completed dependencies are ready."""
        r1 = client.post("/api/tickets", json={"objective": "First"})
        r2 = client.post("/api/tickets", json={"objective": "Second"})
        ticket1_id = r1.json()["id"]
        ticket2_id = r2.json()["id"]

        # Add dependency
        client.post(
            f"/api/tickets/{ticket2_id}/dependencies",
            json={"depends_on_id": ticket1_id},
        )

        # ticket1 is ready (no deps), ticket2 is not (pending dep)
        response = client.get("/api/tickets/ready")
        data = response.json()
        assert data["total"] == 1
        assert data["tickets"][0]["id"] == ticket1_id

        # Complete ticket1
        client.patch(f"/api/tickets/{ticket1_id}", json={"status": "completed"})

        # Now only ticket2 is ready (ticket1 is completed, not pending)
        response = client.get("/api/tickets/ready")
        data = response.json()
        assert data["total"] == 1
        assert data["tickets"][0]["id"] == ticket2_id
