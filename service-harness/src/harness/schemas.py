"""Pydantic schemas for API request/response validation."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Any, Dict

from pydantic import BaseModel, Field, ConfigDict

from harness.models import (
    TicketStatus,
    TicketPriority,
    TicketSourceType,
    TicketEventType,
)


# ============================================================================
# Base schemas with common configuration
# ============================================================================


class HarnessBaseModel(BaseModel):
    """Base model with common configuration."""

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# Ticket schemas
# ============================================================================


class TicketCreate(BaseModel):
    """Schema for creating a ticket."""

    objective: str = Field(..., min_length=1, max_length=5000)
    success_criteria: Optional[str] = Field(None, max_length=5000)
    context: Optional[Dict[str, Any]] = None
    priority: TicketPriority = TicketPriority.MEDIUM
    source_type: TicketSourceType = TicketSourceType.HUMAN
    source_id: Optional[str] = Field(None, max_length=255)


class TicketUpdate(BaseModel):
    """Schema for updating a ticket."""

    objective: Optional[str] = Field(None, min_length=1, max_length=5000)
    success_criteria: Optional[str] = Field(None, max_length=5000)
    context: Optional[Dict[str, Any]] = None
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None


class TicketEventCreate(BaseModel):
    """Schema for creating a ticket event."""

    event_type: TicketEventType
    data: Optional[Dict[str, Any]] = None


class TicketEventResponse(HarnessBaseModel):
    """Schema for a ticket event response."""

    id: int
    ticket_id: int
    event_type: TicketEventType
    data: Optional[Dict[str, Any]]
    created_at: datetime


class TicketDependencyCreate(BaseModel):
    """Schema for adding a ticket dependency."""

    depends_on_id: int


class TicketDependencyResponse(HarnessBaseModel):
    """Schema for a ticket dependency response."""

    ticket_id: int
    depends_on_id: int
    created_at: datetime


class TicketResponse(HarnessBaseModel):
    """Schema for a ticket response."""

    id: int
    objective: str
    success_criteria: Optional[str]
    context: Optional[Dict[str, Any]]
    status: TicketStatus
    priority: TicketPriority
    source_type: TicketSourceType
    source_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime]


class TicketDetailResponse(TicketResponse):
    """Schema for a ticket response with events and dependencies."""

    events: List[TicketEventResponse] = []
    dependencies: List[TicketDependencyResponse] = []
    is_ready: bool = False


class TicketListResponse(BaseModel):
    """Schema for paginated ticket list response."""

    tickets: List[TicketResponse]
    total: int
    limit: int
    offset: int


# ============================================================================
# SLO schemas
# ============================================================================


class SLOCreate(BaseModel):
    """Schema for creating an SLO."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    target: float = Field(..., gt=0, le=1)  # 0 < target <= 1
    window_days: int = Field(30, gt=0, le=365)
    metric_query: str = Field(..., min_length=1, max_length=10000)
    burn_rate_thresholds: Optional[Dict[str, float]] = None
    enabled: bool = True


class SLOUpdate(BaseModel):
    """Schema for updating an SLO."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    target: Optional[float] = Field(None, gt=0, le=1)
    window_days: Optional[int] = Field(None, gt=0, le=365)
    metric_query: Optional[str] = Field(None, min_length=1, max_length=10000)
    burn_rate_thresholds: Optional[Dict[str, float]] = None
    enabled: Optional[bool] = None


class SLOResponse(HarnessBaseModel):
    """Schema for an SLO response."""

    id: int
    name: str
    description: Optional[str]
    target: float
    window_days: int
    metric_query: str
    burn_rate_thresholds: Optional[Dict[str, float]]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class SLOListResponse(BaseModel):
    """Schema for paginated SLO list response."""

    slos: List[SLOResponse]
    total: int


# ============================================================================
# Invariant schemas
# ============================================================================


class InvariantCreate(BaseModel):
    """Schema for creating an invariant."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    query: str = Field(..., min_length=1, max_length=10000)
    condition: str = Field(..., min_length=1, max_length=255)
    enabled: bool = True


class InvariantUpdate(BaseModel):
    """Schema for updating an invariant."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    query: Optional[str] = Field(None, min_length=1, max_length=10000)
    condition: Optional[str] = Field(None, min_length=1, max_length=255)
    enabled: Optional[bool] = None


class InvariantResponse(HarnessBaseModel):
    """Schema for an invariant response."""

    id: int
    name: str
    description: Optional[str]
    query: str
    condition: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class InvariantListResponse(BaseModel):
    """Schema for paginated invariant list response."""

    invariants: List[InvariantResponse]
    total: int


# ============================================================================
# Health and stats schemas
# ============================================================================


class HealthResponse(BaseModel):
    """Schema for health check response."""

    status: str = "ok"
    version: str


class StatsResponse(BaseModel):
    """Schema for dashboard statistics."""

    tickets_pending: int
    tickets_in_progress: int
    tickets_completed_today: int
    tickets_failed_today: int
    slos_enabled: int
    slos_breaching: int
    invariants_enabled: int
    invariants_failing: int


# ============================================================================
# Error schemas
# ============================================================================


class ErrorResponse(BaseModel):
    """Schema for error responses."""

    detail: str
    code: Optional[str] = None
