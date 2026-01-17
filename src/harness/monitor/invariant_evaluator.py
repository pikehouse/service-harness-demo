"""Invariant evaluator for checking operational conditions."""

from typing import Optional, List
from datetime import datetime
from dataclasses import dataclass
import logging
import operator
import re

from sqlalchemy.orm import Session

from harness.models import Invariant, Ticket, TicketEvent, TicketStatus, TicketPriority, TicketSourceType, TicketEventType
from harness.grafana import PrometheusClient

logger = logging.getLogger(__name__)


# Mapping of condition operators
OPERATORS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}

# Regex to parse conditions like "> 20", "== 0", "<= 100"
CONDITION_PATTERN = re.compile(r"^\s*(>=|<=|>|<|==|!=)\s*(-?\d+(?:\.\d+)?)\s*$")


@dataclass
class InvariantEvaluation:
    """Result of evaluating an invariant."""

    invariant_id: int
    invariant_name: str
    query: str
    condition: str
    current_value: Optional[float]
    threshold_value: float
    is_passing: bool
    evaluated_at: datetime
    error: Optional[str] = None


def parse_condition(condition: str) -> tuple:
    """Parse a condition string into (operator_func, threshold_value).

    Args:
        condition: Condition string like "> 20", "== 0", "<= 100"

    Returns:
        Tuple of (operator function, threshold value)

    Raises:
        ValueError: If condition format is invalid
    """
    match = CONDITION_PATTERN.match(condition)
    if not match:
        raise ValueError(f"Invalid condition format: {condition}. Expected format like '> 20', '== 0', '<= 100'")

    op_str, value_str = match.groups()
    op_func = OPERATORS[op_str]
    threshold = float(value_str)

    return op_func, threshold


class InvariantEvaluator:
    """Evaluates invariants by querying Prometheus and checking conditions.

    Invariants are binary pass/fail conditions that must always hold.
    Examples:
    - Capacity headroom > 20%
    - Error count == 0
    - Connection pool usage < 80%
    """

    def __init__(self, prometheus_client: Optional[PrometheusClient] = None):
        """Initialize the invariant evaluator.

        Args:
            prometheus_client: Optional Prometheus client (creates one if not provided)
        """
        self._prometheus = prometheus_client or PrometheusClient()
        self._owns_client = prometheus_client is None

    def close(self):
        """Close resources."""
        if self._owns_client:
            self._prometheus.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def evaluate(self, invariant: Invariant) -> InvariantEvaluation:
        """Evaluate a single invariant.

        Args:
            invariant: The invariant to evaluate

        Returns:
            InvariantEvaluation with current status
        """
        now = datetime.utcnow()

        try:
            # Parse the condition
            op_func, threshold = parse_condition(invariant.condition)

            # Query the current value
            current_value = self._prometheus.get_metric_value(invariant.query)

            if current_value is None:
                return InvariantEvaluation(
                    invariant_id=invariant.id,
                    invariant_name=invariant.name,
                    query=invariant.query,
                    condition=invariant.condition,
                    current_value=None,
                    threshold_value=threshold,
                    is_passing=True,  # No data = assume passing (could be configurable)
                    evaluated_at=now,
                    error="No data returned from Prometheus",
                )

            # Check if the condition passes
            is_passing = op_func(current_value, threshold)

            return InvariantEvaluation(
                invariant_id=invariant.id,
                invariant_name=invariant.name,
                query=invariant.query,
                condition=invariant.condition,
                current_value=current_value,
                threshold_value=threshold,
                is_passing=is_passing,
                evaluated_at=now,
            )

        except ValueError as e:
            logger.error(f"Invalid condition for invariant {invariant.name}: {e}")
            return InvariantEvaluation(
                invariant_id=invariant.id,
                invariant_name=invariant.name,
                query=invariant.query,
                condition=invariant.condition,
                current_value=None,
                threshold_value=0,
                is_passing=True,  # Invalid condition = assume passing
                evaluated_at=now,
                error=str(e),
            )
        except Exception as e:
            logger.exception(f"Error evaluating invariant {invariant.name}")
            return InvariantEvaluation(
                invariant_id=invariant.id,
                invariant_name=invariant.name,
                query=invariant.query,
                condition=invariant.condition,
                current_value=None,
                threshold_value=0,
                is_passing=True,
                evaluated_at=now,
                error=str(e),
            )

    def evaluate_all(self, db: Session) -> List[InvariantEvaluation]:
        """Evaluate all enabled invariants.

        Args:
            db: Database session

        Returns:
            List of InvariantEvaluation results
        """
        from sqlalchemy import select

        invariants = db.scalars(select(Invariant).where(Invariant.enabled == True)).all()
        return [self.evaluate(inv) for inv in invariants]

    def create_violation_ticket(
        self,
        db: Session,
        evaluation: InvariantEvaluation,
    ) -> Optional[Ticket]:
        """Create a ticket for an invariant violation.

        Args:
            db: Database session
            evaluation: The invariant evaluation result

        Returns:
            Created ticket, or None if passing or ticket already exists
        """
        if evaluation.is_passing:
            return None

        # Check if there's already an open ticket for this invariant
        from sqlalchemy import select, and_

        existing = db.scalar(
            select(Ticket).where(
                and_(
                    Ticket.source_type == TicketSourceType.INVARIANT_VIOLATION,
                    Ticket.source_id == str(evaluation.invariant_id),
                    Ticket.status.in_([TicketStatus.PENDING, TicketStatus.IN_PROGRESS]),
                )
            )
        )

        if existing:
            logger.info(f"Ticket already exists for invariant {evaluation.invariant_name} violation")
            return None

        # Invariant violations are high priority by default
        ticket = Ticket(
            objective=f"Fix invariant violation: {evaluation.invariant_name}",
            success_criteria=f"Invariant {evaluation.invariant_name} condition ({evaluation.condition}) is satisfied",
            context={
                "invariant_id": evaluation.invariant_id,
                "invariant_name": evaluation.invariant_name,
                "query": evaluation.query,
                "condition": evaluation.condition,
                "current_value": evaluation.current_value,
                "threshold_value": evaluation.threshold_value,
                "detected_at": evaluation.evaluated_at.isoformat(),
            },
            status=TicketStatus.PENDING,
            priority=TicketPriority.HIGH,
            source_type=TicketSourceType.INVARIANT_VIOLATION,
            source_id=str(evaluation.invariant_id),
        )
        db.add(ticket)
        db.flush()

        # Add created event
        event = TicketEvent(
            ticket_id=ticket.id,
            event_type=TicketEventType.CREATED,
            data={
                "source": "invariant_evaluator",
                "current_value": evaluation.current_value,
                "threshold_value": evaluation.threshold_value,
            },
        )
        db.add(event)
        db.commit()

        logger.info(f"Created ticket {ticket.id} for invariant {evaluation.invariant_name} violation")
        return ticket
