"""Ticket API routes."""

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload

from harness.database import get_db
from harness.models import (
    Ticket,
    TicketEvent,
    TicketDependency,
    TicketStatus,
    TicketSourceType,
    TicketEventType,
)
from harness.schemas import (
    TicketCreate,
    TicketUpdate,
    TicketResponse,
    TicketDetailResponse,
    TicketListResponse,
    TicketEventCreate,
    TicketEventResponse,
    TicketDependencyCreate,
    TicketDependencyResponse,
)

router = APIRouter()


def get_ticket_or_404(db: Session, ticket_id: int) -> Ticket:
    """Get a ticket by ID or raise 404."""
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    return ticket


@router.get("", response_model=TicketListResponse)
def list_tickets(
    status: Optional[TicketStatus] = None,
    source_type: Optional[TicketSourceType] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List tickets with optional filtering."""
    query = select(Ticket)

    # Handle special 'ready' status filter
    if status and status.value == "ready":
        # Ready = pending + all dependencies completed
        # First get all pending tickets
        query = query.where(Ticket.status == TicketStatus.PENDING)
    elif status:
        query = query.where(Ticket.status == status)

    if source_type:
        query = query.where(Ticket.source_type == source_type)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query)

    # Get paginated results
    query = query.order_by(Ticket.created_at.desc()).offset(offset).limit(limit)
    tickets = list(db.scalars(query).all())

    # If filtering by 'ready', filter out tickets with incomplete dependencies
    if status and status.value == "ready":
        # Load dependencies for filtering
        ready_tickets = []
        for ticket in tickets:
            db.refresh(ticket, ["dependencies"])
            if ticket.is_ready():
                ready_tickets.append(ticket)
        tickets = ready_tickets
        total = len(ready_tickets)  # Adjust total for ready filter

    return TicketListResponse(
        tickets=[TicketResponse.model_validate(t) for t in tickets],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/ready", response_model=TicketListResponse)
def list_ready_tickets(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List tickets that are ready to be worked on.

    A ticket is ready when:
    - Status is PENDING
    - All dependencies have status COMPLETED
    """
    # Get all pending tickets with their dependencies
    query = (
        select(Ticket)
        .where(Ticket.status == TicketStatus.PENDING)
        .options(selectinload(Ticket.dependencies).selectinload(TicketDependency.depends_on))
        .order_by(Ticket.created_at.desc())
    )
    all_pending = list(db.scalars(query).all())

    # Filter to only ready tickets
    ready_tickets = [t for t in all_pending if t.is_ready()]
    total = len(ready_tickets)

    # Apply pagination
    paginated = ready_tickets[offset : offset + limit]

    return TicketListResponse(
        tickets=[TicketResponse.model_validate(t) for t in paginated],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=TicketDetailResponse, status_code=201)
def create_ticket(
    ticket_data: TicketCreate,
    db: Session = Depends(get_db),
):
    """Create a new ticket."""
    ticket = Ticket(**ticket_data.model_dump())
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    # Add created event
    event = TicketEvent(
        ticket_id=ticket.id,
        event_type=TicketEventType.CREATED,
        data={"initial_status": ticket.status.value, "priority": ticket.priority.value},
    )
    db.add(event)
    db.commit()

    db.refresh(ticket, ["events", "dependencies"])
    return TicketDetailResponse(
        **TicketResponse.model_validate(ticket).model_dump(),
        events=[TicketEventResponse.model_validate(e) for e in ticket.events],
        dependencies=[TicketDependencyResponse.model_validate(d) for d in ticket.dependencies],
        is_ready=ticket.is_ready(),
    )


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
def get_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
):
    """Get a ticket by ID with events and dependencies."""
    ticket = get_ticket_or_404(db, ticket_id)
    db.refresh(ticket, ["events", "dependencies"])

    return TicketDetailResponse(
        **TicketResponse.model_validate(ticket).model_dump(),
        events=[TicketEventResponse.model_validate(e) for e in ticket.events],
        dependencies=[TicketDependencyResponse.model_validate(d) for d in ticket.dependencies],
        is_ready=ticket.is_ready(),
    )


@router.patch("/{ticket_id}", response_model=TicketDetailResponse)
def update_ticket(
    ticket_id: int,
    ticket_data: TicketUpdate,
    db: Session = Depends(get_db),
):
    """Update a ticket."""
    ticket = get_ticket_or_404(db, ticket_id)

    update_data = ticket_data.model_dump(exclude_unset=True)

    # Track status change for event
    old_status = ticket.status
    status_changed = "status" in update_data and update_data["status"] != old_status

    # Track priority change for event
    old_priority = ticket.priority
    priority_changed = "priority" in update_data and update_data["priority"] != old_priority

    # Apply updates
    for field, value in update_data.items():
        setattr(ticket, field, value)

    db.commit()
    db.refresh(ticket, ["events", "dependencies"])

    # Add status change event
    if status_changed:
        event = TicketEvent(
            ticket_id=ticket.id,
            event_type=TicketEventType.STATUS_CHANGED,
            data={"old_status": old_status.value, "new_status": ticket.status.value},
        )
        db.add(event)
        db.commit()
        db.refresh(ticket, ["events"])

    # Add priority change event
    if priority_changed:
        event = TicketEvent(
            ticket_id=ticket.id,
            event_type=TicketEventType.PRIORITY_CHANGED,
            data={"old_priority": old_priority.value, "new_priority": ticket.priority.value},
        )
        db.add(event)
        db.commit()
        db.refresh(ticket, ["events"])

    return TicketDetailResponse(
        **TicketResponse.model_validate(ticket).model_dump(),
        events=[TicketEventResponse.model_validate(e) for e in ticket.events],
        dependencies=[TicketDependencyResponse.model_validate(d) for d in ticket.dependencies],
        is_ready=ticket.is_ready(),
    )


# ============================================================================
# Events
# ============================================================================


@router.get("/{ticket_id}/events", response_model=List[TicketEventResponse])
def list_ticket_events(
    ticket_id: int,
    db: Session = Depends(get_db),
):
    """Get all events for a ticket (trajectory)."""
    ticket = get_ticket_or_404(db, ticket_id)
    db.refresh(ticket, ["events"])
    return [TicketEventResponse.model_validate(e) for e in ticket.events]


@router.post("/{ticket_id}/events", response_model=TicketEventResponse, status_code=201)
def create_ticket_event(
    ticket_id: int,
    event_data: TicketEventCreate,
    db: Session = Depends(get_db),
):
    """Add an event to a ticket."""
    ticket = get_ticket_or_404(db, ticket_id)

    event = TicketEvent(
        ticket_id=ticket.id,
        event_type=event_data.event_type,
        data=event_data.data,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    return TicketEventResponse.model_validate(event)


# ============================================================================
# Dependencies
# ============================================================================


@router.get("/{ticket_id}/dependencies", response_model=List[TicketDependencyResponse])
def list_ticket_dependencies(
    ticket_id: int,
    db: Session = Depends(get_db),
):
    """Get all dependencies for a ticket."""
    ticket = get_ticket_or_404(db, ticket_id)
    db.refresh(ticket, ["dependencies"])
    return [TicketDependencyResponse.model_validate(d) for d in ticket.dependencies]


@router.post("/{ticket_id}/dependencies", response_model=TicketDependencyResponse, status_code=201)
def add_ticket_dependency(
    ticket_id: int,
    dep_data: TicketDependencyCreate,
    db: Session = Depends(get_db),
):
    """Add a dependency to a ticket."""
    ticket = get_ticket_or_404(db, ticket_id)
    depends_on = get_ticket_or_404(db, dep_data.depends_on_id)

    # Prevent self-dependency
    if ticket_id == dep_data.depends_on_id:
        raise HTTPException(status_code=400, detail="A ticket cannot depend on itself")

    # Check if dependency already exists
    existing = db.scalar(
        select(TicketDependency).where(
            TicketDependency.ticket_id == ticket_id,
            TicketDependency.depends_on_id == dep_data.depends_on_id,
        )
    )
    if existing:
        raise HTTPException(status_code=400, detail="Dependency already exists")

    dependency = TicketDependency(
        ticket_id=ticket_id,
        depends_on_id=dep_data.depends_on_id,
    )
    db.add(dependency)

    # Add event
    event = TicketEvent(
        ticket_id=ticket_id,
        event_type=TicketEventType.DEPENDENCY_ADDED,
        data={"depends_on_id": dep_data.depends_on_id, "depends_on_objective": depends_on.objective[:100]},
    )
    db.add(event)

    db.commit()
    db.refresh(dependency)

    return TicketDependencyResponse.model_validate(dependency)


@router.delete("/{ticket_id}/dependencies/{depends_on_id}", status_code=204)
def remove_ticket_dependency(
    ticket_id: int,
    depends_on_id: int,
    db: Session = Depends(get_db),
):
    """Remove a dependency from a ticket."""
    ticket = get_ticket_or_404(db, ticket_id)

    dependency = db.scalar(
        select(TicketDependency).where(
            TicketDependency.ticket_id == ticket_id,
            TicketDependency.depends_on_id == depends_on_id,
        )
    )
    if not dependency:
        raise HTTPException(status_code=404, detail="Dependency not found")

    db.delete(dependency)

    # Add event
    event = TicketEvent(
        ticket_id=ticket_id,
        event_type=TicketEventType.DEPENDENCY_REMOVED,
        data={"depends_on_id": depends_on_id},
    )
    db.add(event)

    db.commit()
