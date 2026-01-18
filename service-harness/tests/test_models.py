"""Tests for database models."""

import pytest
from datetime import datetime

from harness.models import (
    Ticket,
    TicketEvent,
    TicketDependency,
    SLO,
    Invariant,
    TicketStatus,
    TicketPriority,
    TicketSourceType,
    TicketEventType,
)


class TestTicket:
    """Tests for the Ticket model."""

    def test_create_ticket(self, db_session):
        """Test creating a basic ticket."""
        ticket = Ticket(
            objective="Fix the bug",
            success_criteria="Tests pass",
            priority=TicketPriority.HIGH,
        )
        db_session.add(ticket)
        db_session.commit()

        assert ticket.id is not None
        assert ticket.objective == "Fix the bug"
        assert ticket.status == TicketStatus.PENDING
        assert ticket.priority == TicketPriority.HIGH
        assert ticket.source_type == TicketSourceType.HUMAN
        assert ticket.created_at is not None

    def test_ticket_defaults(self, db_session):
        """Test that ticket defaults are set correctly."""
        ticket = Ticket(objective="Test defaults")
        db_session.add(ticket)
        db_session.commit()

        assert ticket.status == TicketStatus.PENDING
        assert ticket.priority == TicketPriority.MEDIUM
        assert ticket.source_type == TicketSourceType.HUMAN
        assert ticket.context == {} or ticket.context is None
        assert ticket.resolved_at is None

    def test_ticket_with_context(self, db_session):
        """Test ticket with JSON context."""
        ticket = Ticket(
            objective="Debug issue",
            context={"error": "NullPointerException", "file": "main.py", "line": 42},
        )
        db_session.add(ticket)
        db_session.commit()

        db_session.refresh(ticket)
        assert ticket.context["error"] == "NullPointerException"
        assert ticket.context["line"] == 42

    def test_ticket_status_update(self, db_session):
        """Test updating ticket status."""
        ticket = Ticket(objective="Status test")
        db_session.add(ticket)
        db_session.commit()

        ticket.status = TicketStatus.IN_PROGRESS
        db_session.commit()

        db_session.refresh(ticket)
        assert ticket.status == TicketStatus.IN_PROGRESS

    def test_ticket_is_ready_no_dependencies(self, db_session):
        """Test is_ready with no dependencies."""
        ticket = Ticket(objective="Ready test", status=TicketStatus.PENDING)
        db_session.add(ticket)
        db_session.commit()

        assert ticket.is_ready() is True

    def test_ticket_is_ready_in_progress_not_ready(self, db_session):
        """Test is_ready returns False when in_progress."""
        ticket = Ticket(objective="In progress test", status=TicketStatus.IN_PROGRESS)
        db_session.add(ticket)
        db_session.commit()

        assert ticket.is_ready() is False


class TestTicketDependencies:
    """Tests for ticket dependency relationships."""

    def test_add_dependency(self, db_session):
        """Test adding a dependency between tickets."""
        ticket1 = Ticket(objective="First task")
        ticket2 = Ticket(objective="Depends on first")
        db_session.add_all([ticket1, ticket2])
        db_session.commit()

        dep = TicketDependency(ticket_id=ticket2.id, depends_on_id=ticket1.id)
        db_session.add(dep)
        db_session.commit()

        db_session.refresh(ticket2)
        assert len(ticket2.dependencies) == 1
        assert ticket2.dependencies[0].depends_on_id == ticket1.id

    def test_is_ready_with_pending_dependency(self, db_session):
        """Test is_ready returns False when dependency is pending."""
        ticket1 = Ticket(objective="First task", status=TicketStatus.PENDING)
        ticket2 = Ticket(objective="Depends on first", status=TicketStatus.PENDING)
        db_session.add_all([ticket1, ticket2])
        db_session.commit()

        dep = TicketDependency(ticket_id=ticket2.id, depends_on_id=ticket1.id)
        db_session.add(dep)
        db_session.commit()

        db_session.refresh(ticket2)
        assert ticket2.is_ready() is False

    def test_is_ready_with_completed_dependency(self, db_session):
        """Test is_ready returns True when dependency is completed."""
        ticket1 = Ticket(objective="First task", status=TicketStatus.COMPLETED)
        ticket2 = Ticket(objective="Depends on first", status=TicketStatus.PENDING)
        db_session.add_all([ticket1, ticket2])
        db_session.commit()

        dep = TicketDependency(ticket_id=ticket2.id, depends_on_id=ticket1.id)
        db_session.add(dep)
        db_session.commit()

        db_session.refresh(ticket2)
        assert ticket2.is_ready() is True

    def test_multiple_dependencies(self, db_session):
        """Test ticket with multiple dependencies."""
        ticket1 = Ticket(objective="First task", status=TicketStatus.COMPLETED)
        ticket2 = Ticket(objective="Second task", status=TicketStatus.PENDING)
        ticket3 = Ticket(objective="Depends on both", status=TicketStatus.PENDING)
        db_session.add_all([ticket1, ticket2, ticket3])
        db_session.commit()

        dep1 = TicketDependency(ticket_id=ticket3.id, depends_on_id=ticket1.id)
        dep2 = TicketDependency(ticket_id=ticket3.id, depends_on_id=ticket2.id)
        db_session.add_all([dep1, dep2])
        db_session.commit()

        db_session.refresh(ticket3)
        # ticket2 is still pending, so ticket3 is not ready
        assert ticket3.is_ready() is False

        # Complete ticket2
        ticket2.status = TicketStatus.COMPLETED
        db_session.commit()

        db_session.refresh(ticket3)
        assert ticket3.is_ready() is True

    def test_dependency_cascade_delete(self, db_session):
        """Test that dependencies are deleted when a ticket is deleted."""
        ticket1 = Ticket(objective="First task")
        ticket2 = Ticket(objective="Depends on first")
        db_session.add_all([ticket1, ticket2])
        db_session.commit()

        dep = TicketDependency(ticket_id=ticket2.id, depends_on_id=ticket1.id)
        db_session.add(dep)
        db_session.commit()

        # Delete ticket2
        db_session.delete(ticket2)
        db_session.commit()

        # Dependency should be gone
        deps = db_session.query(TicketDependency).all()
        assert len(deps) == 0


class TestTicketEvent:
    """Tests for the TicketEvent model."""

    def test_create_event(self, db_session):
        """Test creating a ticket event."""
        ticket = Ticket(objective="Event test")
        db_session.add(ticket)
        db_session.commit()

        event = TicketEvent(
            ticket_id=ticket.id,
            event_type=TicketEventType.CREATED,
            data={"initial_status": "pending"},
        )
        db_session.add(event)
        db_session.commit()

        assert event.id is not None
        assert event.ticket_id == ticket.id
        assert event.event_type == TicketEventType.CREATED
        assert event.data["initial_status"] == "pending"

    def test_ticket_events_relationship(self, db_session):
        """Test that events are accessible from ticket."""
        ticket = Ticket(objective="Multiple events")
        db_session.add(ticket)
        db_session.commit()

        event1 = TicketEvent(
            ticket_id=ticket.id,
            event_type=TicketEventType.CREATED,
        )
        event2 = TicketEvent(
            ticket_id=ticket.id,
            event_type=TicketEventType.STATUS_CHANGED,
            data={"old": "pending", "new": "in_progress"},
        )
        db_session.add_all([event1, event2])
        db_session.commit()

        db_session.refresh(ticket)
        assert len(ticket.events) == 2

    def test_event_cascade_delete(self, db_session):
        """Test that events are deleted when ticket is deleted."""
        ticket = Ticket(objective="Cascade test")
        db_session.add(ticket)
        db_session.commit()

        event = TicketEvent(
            ticket_id=ticket.id,
            event_type=TicketEventType.CREATED,
        )
        db_session.add(event)
        db_session.commit()

        # Delete ticket
        db_session.delete(ticket)
        db_session.commit()

        # Events should be gone
        events = db_session.query(TicketEvent).all()
        assert len(events) == 0


class TestSLO:
    """Tests for the SLO model."""

    def test_create_slo(self, db_session):
        """Test creating an SLO."""
        slo = SLO(
            name="availability",
            description="Service availability SLO",
            target=0.999,
            window_days=30,
            metric_query='sum(rate(http_requests_total{status!~"5.."}[5m])) / sum(rate(http_requests_total[5m]))',
            burn_rate_thresholds={"fast": 14.4, "slow": 1},
        )
        db_session.add(slo)
        db_session.commit()

        assert slo.id is not None
        assert slo.name == "availability"
        assert slo.target == 0.999
        assert slo.window_days == 30
        assert slo.enabled is True
        assert slo.burn_rate_thresholds["fast"] == 14.4

    def test_slo_defaults(self, db_session):
        """Test SLO default values."""
        slo = SLO(
            name="latency",
            target=0.95,
            metric_query="histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))",
        )
        db_session.add(slo)
        db_session.commit()

        assert slo.window_days == 30
        assert slo.enabled is True

    def test_slo_unique_name(self, db_session):
        """Test that SLO names must be unique."""
        slo1 = SLO(name="unique_slo", target=0.99, metric_query="query1")
        db_session.add(slo1)
        db_session.commit()

        slo2 = SLO(name="unique_slo", target=0.95, metric_query="query2")
        db_session.add(slo2)
        with pytest.raises(Exception):  # IntegrityError
            db_session.commit()


class TestInvariant:
    """Tests for the Invariant model."""

    def test_create_invariant(self, db_session):
        """Test creating an invariant."""
        invariant = Invariant(
            name="capacity_headroom",
            description="Ensure capacity headroom > 20%",
            query="(1 - (sum(container_memory_usage_bytes) / sum(container_spec_memory_limit_bytes))) * 100",
            condition="> 20",
        )
        db_session.add(invariant)
        db_session.commit()

        assert invariant.id is not None
        assert invariant.name == "capacity_headroom"
        assert invariant.condition == "> 20"
        assert invariant.enabled is True

    def test_invariant_defaults(self, db_session):
        """Test invariant default values."""
        invariant = Invariant(
            name="no_errors",
            query='count(rate(error_total[1m]))',
            condition="== 0",
        )
        db_session.add(invariant)
        db_session.commit()

        assert invariant.enabled is True

    def test_invariant_unique_name(self, db_session):
        """Test that invariant names must be unique."""
        inv1 = Invariant(name="unique_inv", query="query1", condition="> 0")
        db_session.add(inv1)
        db_session.commit()

        inv2 = Invariant(name="unique_inv", query="query2", condition="< 100")
        db_session.add(inv2)
        with pytest.raises(Exception):  # IntegrityError
            db_session.commit()

    def test_invariant_disable(self, db_session):
        """Test disabling an invariant."""
        invariant = Invariant(
            name="disable_test",
            query="query",
            condition="> 0",
            enabled=True,
        )
        db_session.add(invariant)
        db_session.commit()

        invariant.enabled = False
        db_session.commit()

        db_session.refresh(invariant)
        assert invariant.enabled is False
