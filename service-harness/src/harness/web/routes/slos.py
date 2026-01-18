"""SLO API routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from harness.database import get_db
from harness.models import SLO
from harness.schemas import (
    SLOCreate,
    SLOUpdate,
    SLOResponse,
    SLOListResponse,
)

router = APIRouter()


def get_slo_or_404(db: Session, slo_id: int) -> SLO:
    """Get an SLO by ID or raise 404."""
    slo = db.get(SLO, slo_id)
    if not slo:
        raise HTTPException(status_code=404, detail=f"SLO {slo_id} not found")
    return slo


@router.get("", response_model=SLOListResponse)
def list_slos(
    enabled: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    """List all SLOs with optional filtering."""
    query = select(SLO)

    if enabled is not None:
        query = query.where(SLO.enabled == enabled)

    query = query.order_by(SLO.name)

    slos = list(db.scalars(query).all())
    total = len(slos)

    return SLOListResponse(
        slos=[SLOResponse.model_validate(s) for s in slos],
        total=total,
    )


@router.post("", response_model=SLOResponse, status_code=201)
def create_slo(
    slo_data: SLOCreate,
    db: Session = Depends(get_db),
):
    """Create a new SLO."""
    # Check for duplicate name
    existing = db.scalar(select(SLO).where(SLO.name == slo_data.name))
    if existing:
        raise HTTPException(status_code=400, detail=f"SLO with name '{slo_data.name}' already exists")

    slo = SLO(**slo_data.model_dump())
    db.add(slo)
    db.commit()
    db.refresh(slo)

    return SLOResponse.model_validate(slo)


@router.get("/{slo_id}", response_model=SLOResponse)
def get_slo(
    slo_id: int,
    db: Session = Depends(get_db),
):
    """Get an SLO by ID."""
    slo = get_slo_or_404(db, slo_id)
    return SLOResponse.model_validate(slo)


@router.patch("/{slo_id}", response_model=SLOResponse)
def update_slo(
    slo_id: int,
    slo_data: SLOUpdate,
    db: Session = Depends(get_db),
):
    """Update an SLO."""
    slo = get_slo_or_404(db, slo_id)

    update_data = slo_data.model_dump(exclude_unset=True)

    # Check for duplicate name if updating name
    if "name" in update_data and update_data["name"] != slo.name:
        existing = db.scalar(select(SLO).where(SLO.name == update_data["name"]))
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"SLO with name '{update_data['name']}' already exists",
            )

    for field, value in update_data.items():
        setattr(slo, field, value)

    db.commit()
    db.refresh(slo)

    return SLOResponse.model_validate(slo)


@router.delete("/{slo_id}", status_code=204)
def delete_slo(
    slo_id: int,
    db: Session = Depends(get_db),
):
    """Delete (disable) an SLO.

    This performs a soft delete by setting enabled=False.
    """
    slo = get_slo_or_404(db, slo_id)
    slo.enabled = False
    db.commit()
