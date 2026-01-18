"""Invariant API routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from harness.database import get_db
from harness.models import Invariant
from harness.schemas import (
    InvariantCreate,
    InvariantUpdate,
    InvariantResponse,
    InvariantListResponse,
)

router = APIRouter()


def get_invariant_or_404(db: Session, invariant_id: int) -> Invariant:
    """Get an invariant by ID or raise 404."""
    invariant = db.get(Invariant, invariant_id)
    if not invariant:
        raise HTTPException(status_code=404, detail=f"Invariant {invariant_id} not found")
    return invariant


@router.get("", response_model=InvariantListResponse)
def list_invariants(
    enabled: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    """List all invariants with optional filtering."""
    query = select(Invariant)

    if enabled is not None:
        query = query.where(Invariant.enabled == enabled)

    query = query.order_by(Invariant.name)

    invariants = list(db.scalars(query).all())
    total = len(invariants)

    return InvariantListResponse(
        invariants=[InvariantResponse.model_validate(i) for i in invariants],
        total=total,
    )


@router.post("", response_model=InvariantResponse, status_code=201)
def create_invariant(
    invariant_data: InvariantCreate,
    db: Session = Depends(get_db),
):
    """Create a new invariant."""
    # Check for duplicate name
    existing = db.scalar(select(Invariant).where(Invariant.name == invariant_data.name))
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Invariant with name '{invariant_data.name}' already exists",
        )

    invariant = Invariant(**invariant_data.model_dump())
    db.add(invariant)
    db.commit()
    db.refresh(invariant)

    return InvariantResponse.model_validate(invariant)


@router.get("/{invariant_id}", response_model=InvariantResponse)
def get_invariant(
    invariant_id: int,
    db: Session = Depends(get_db),
):
    """Get an invariant by ID."""
    invariant = get_invariant_or_404(db, invariant_id)
    return InvariantResponse.model_validate(invariant)


@router.patch("/{invariant_id}", response_model=InvariantResponse)
def update_invariant(
    invariant_id: int,
    invariant_data: InvariantUpdate,
    db: Session = Depends(get_db),
):
    """Update an invariant."""
    invariant = get_invariant_or_404(db, invariant_id)

    update_data = invariant_data.model_dump(exclude_unset=True)

    # Check for duplicate name if updating name
    if "name" in update_data and update_data["name"] != invariant.name:
        existing = db.scalar(select(Invariant).where(Invariant.name == update_data["name"]))
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Invariant with name '{update_data['name']}' already exists",
            )

    for field, value in update_data.items():
        setattr(invariant, field, value)

    db.commit()
    db.refresh(invariant)

    return InvariantResponse.model_validate(invariant)


@router.delete("/{invariant_id}", status_code=204)
def delete_invariant(
    invariant_id: int,
    db: Session = Depends(get_db),
):
    """Delete (disable) an invariant.

    This performs a soft delete by setting enabled=False.
    """
    invariant = get_invariant_or_404(db, invariant_id)
    invariant.enabled = False
    db.commit()
