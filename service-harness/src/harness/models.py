"""SQLAlchemy models for the harness database."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional, List, Any

from sqlalchemy import (
    String,
    Text,
    Integer,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Enum,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from harness.database import Base


class TicketStatus(str, enum.Enum):
    """Status values for tickets."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class TicketPriority(str, enum.Enum):
    """Priority levels for tickets."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TicketSourceType(str, enum.Enum):
    """Sources that can create tickets."""

    HUMAN = "human"
    SLO_VIOLATION = "slo_violation"
    INVARIANT_VIOLATION = "invariant_violation"
    ANOMALY = "anomaly"
    SCHEDULED = "scheduled"
    WEBHOOK = "webhook"


class TicketEventType(str, enum.Enum):
    """Types of events that can occur on tickets."""

    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    PRIORITY_CHANGED = "priority_changed"
    NOTE_ADDED = "note_added"
    AGENT_ACTION = "agent_action"
    DEPENDENCY_ADDED = "dependency_added"
    DEPENDENCY_REMOVED = "dependency_removed"
    CONTEXT_UPDATED = "context_updated"


class Ticket(Base):
    """A unit of work for the agent to process."""

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    success_criteria: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=dict)
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus), nullable=False, default=TicketStatus.PENDING
    )
    priority: Mapped[TicketPriority] = mapped_column(
        Enum(TicketPriority), nullable=False, default=TicketPriority.MEDIUM
    )
    source_type: Mapped[TicketSourceType] = mapped_column(
        Enum(TicketSourceType), nullable=False, default=TicketSourceType.HUMAN
    )
    source_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    events: Mapped[List["TicketEvent"]] = relationship(
        "TicketEvent", back_populates="ticket", cascade="all, delete-orphan"
    )

    # Dependencies: tickets this ticket depends on
    dependencies: Mapped[List["TicketDependency"]] = relationship(
        "TicketDependency",
        foreign_keys="TicketDependency.ticket_id",
        back_populates="ticket",
        cascade="all, delete-orphan",
    )

    # Dependents: tickets that depend on this ticket
    dependents: Mapped[List["TicketDependency"]] = relationship(
        "TicketDependency",
        foreign_keys="TicketDependency.depends_on_id",
        back_populates="depends_on",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Ticket(id={self.id}, status={self.status.value}, objective={self.objective[:50]}...)>"

    def is_ready(self) -> bool:
        """Check if this ticket is ready to be worked on.

        A ticket is ready when:
        - Status is PENDING
        - All dependencies are COMPLETED
        """
        if self.status != TicketStatus.PENDING:
            return False
        for dep in self.dependencies:
            if dep.depends_on.status != TicketStatus.COMPLETED:
                return False
        return True


class TicketEvent(Base):
    """An event in a ticket's history (append-only log)."""

    __tablename__ = "ticket_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[TicketEventType] = mapped_column(
        Enum(TicketEventType), nullable=False
    )
    data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationship
    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="events")

    def __repr__(self) -> str:
        return f"<TicketEvent(id={self.id}, ticket_id={self.ticket_id}, type={self.event_type.value})>"


class TicketDependency(Base):
    """A dependency relationship between tickets."""

    __tablename__ = "ticket_dependencies"

    ticket_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    ticket: Mapped["Ticket"] = relationship(
        "Ticket", foreign_keys=[ticket_id], back_populates="dependencies"
    )
    depends_on: Mapped["Ticket"] = relationship(
        "Ticket", foreign_keys=[depends_on_id], back_populates="dependents"
    )

    __table_args__ = (
        UniqueConstraint("ticket_id", "depends_on_id", name="uq_ticket_dependency"),
    )

    def __repr__(self) -> str:
        return f"<TicketDependency(ticket_id={self.ticket_id}, depends_on_id={self.depends_on_id})>"


class SLO(Base):
    """Service Level Objective - a commitment to users."""

    __tablename__ = "slos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target: Mapped[float] = mapped_column(Float, nullable=False)  # e.g., 0.999 for 99.9%
    window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    metric_query: Mapped[str] = mapped_column(Text, nullable=False)  # PromQL query
    burn_rate_thresholds: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, default=dict
    )  # e.g., {"fast": 14, "slow": 1}
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<SLO(id={self.id}, name={self.name}, target={self.target})>"


class Invariant(Base):
    """An operational condition that must always hold."""

    __tablename__ = "invariants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)  # PromQL or LogQL query
    condition: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # e.g., "> 0.2", "== 0"
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Invariant(id={self.id}, name={self.name}, condition={self.condition})>"
