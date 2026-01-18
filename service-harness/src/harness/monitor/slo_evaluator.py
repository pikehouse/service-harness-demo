"""SLO evaluator for calculating burn rates and detecting violations."""

from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import logging

from sqlalchemy.orm import Session

from harness.models import SLO, Ticket, TicketEvent, TicketStatus, TicketPriority, TicketSourceType, TicketEventType
from harness.grafana import PrometheusClient

logger = logging.getLogger(__name__)


@dataclass
class SLOEvaluation:
    """Result of evaluating an SLO."""

    slo_id: int
    slo_name: str
    target: float
    current_value: Optional[float]
    error_budget_remaining: Optional[float]  # Percentage of budget remaining (0-100)
    burn_rate: Optional[float]  # Current burn rate multiplier
    is_violating: bool
    violation_severity: Optional[str]  # "fast", "slow", or None
    evaluated_at: datetime
    error: Optional[str] = None


class SLOEvaluator:
    """Evaluates SLOs by querying Prometheus and calculating burn rates.

    Burn rate is the rate at which the error budget is being consumed.
    - Burn rate of 1 = consuming budget at exactly the sustainable rate
    - Burn rate of 14.4 = consuming budget 14.4x faster (exhausts in ~2 days for 30-day window)
    - Burn rate of 6 = consuming budget 6x faster (exhausts in ~5 days for 30-day window)

    Default thresholds (from Google SRE book):
    - Fast burn (14.4x): Alert within 1 hour, 2% budget consumed
    - Slow burn (6x): Alert within 6 hours, 5% budget consumed
    """

    DEFAULT_BURN_RATE_THRESHOLDS = {
        "fast": {"burn_rate": 14.4, "window_minutes": 60, "priority": TicketPriority.CRITICAL},
        "slow": {"burn_rate": 6.0, "window_minutes": 360, "priority": TicketPriority.HIGH},
    }

    def __init__(self, prometheus_client: Optional[PrometheusClient] = None):
        """Initialize the SLO evaluator.

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

    def evaluate(self, slo: SLO) -> SLOEvaluation:
        """Evaluate a single SLO.

        Args:
            slo: The SLO to evaluate

        Returns:
            SLOEvaluation with current status
        """
        now = datetime.utcnow()

        try:
            # Query the current SLI value
            current_value = self._prometheus.get_metric_value(slo.metric_query)

            if current_value is None:
                return SLOEvaluation(
                    slo_id=slo.id,
                    slo_name=slo.name,
                    target=slo.target,
                    current_value=None,
                    error_budget_remaining=None,
                    burn_rate=None,
                    is_violating=False,
                    violation_severity=None,
                    evaluated_at=now,
                    error="No data returned from Prometheus",
                )

            # Calculate error budget
            # Error budget = 1 - target (e.g., 99.9% target = 0.1% error budget)
            error_budget = 1 - slo.target

            # Calculate how much of the error budget has been consumed
            # If current_value is the success rate, then error_rate = 1 - current_value
            error_rate = 1 - current_value
            budget_consumed = error_rate / error_budget if error_budget > 0 else 0
            budget_remaining = max(0, (1 - budget_consumed) * 100)

            # Calculate burn rate using the configured thresholds
            thresholds = slo.burn_rate_thresholds or self.DEFAULT_BURN_RATE_THRESHOLDS
            burn_rate, violation_severity = self._calculate_burn_rate(
                slo, thresholds, error_budget, now
            )

            is_violating = violation_severity is not None

            return SLOEvaluation(
                slo_id=slo.id,
                slo_name=slo.name,
                target=slo.target,
                current_value=current_value,
                error_budget_remaining=budget_remaining,
                burn_rate=burn_rate,
                is_violating=is_violating,
                violation_severity=violation_severity,
                evaluated_at=now,
            )

        except Exception as e:
            logger.exception(f"Error evaluating SLO {slo.name}")
            return SLOEvaluation(
                slo_id=slo.id,
                slo_name=slo.name,
                target=slo.target,
                current_value=None,
                error_budget_remaining=None,
                burn_rate=None,
                is_violating=False,
                violation_severity=None,
                evaluated_at=now,
                error=str(e),
            )

    def _calculate_burn_rate(
        self,
        slo: SLO,
        thresholds: Dict[str, Any],
        error_budget: float,
        now: datetime,
    ) -> Tuple[Optional[float], Optional[str]]:
        """Calculate the burn rate and determine if any threshold is violated.

        Args:
            slo: The SLO being evaluated
            thresholds: Burn rate threshold configuration
            error_budget: The total error budget (1 - target)
            now: Current time

        Returns:
            Tuple of (burn_rate, violation_severity)
        """
        max_burn_rate = 0.0
        violated_severity = None

        for severity, config in thresholds.items():
            threshold_burn_rate = config.get("burn_rate", 1.0)
            window_minutes = config.get("window_minutes", 60)

            # Query the error rate over the window
            window_start = now - timedelta(minutes=window_minutes)
            try:
                # Modify query to get rate over window
                # Assumes the metric_query returns a ratio/percentage
                range_query = f"avg_over_time(({slo.metric_query})[{window_minutes}m:])"
                window_value = self._prometheus.get_metric_value(range_query)

                if window_value is not None:
                    window_error_rate = 1 - window_value
                    # Burn rate = (error rate over window) / (sustainable error rate)
                    # Sustainable error rate = error_budget / window_days
                    # For a shorter window, we scale proportionally
                    sustainable_rate = error_budget * (window_minutes / (slo.window_days * 24 * 60))
                    burn_rate = window_error_rate / sustainable_rate if sustainable_rate > 0 else 0

                    if burn_rate > max_burn_rate:
                        max_burn_rate = burn_rate

                    if burn_rate >= threshold_burn_rate:
                        # Higher severity wins
                        if violated_severity is None or threshold_burn_rate > thresholds.get(violated_severity, {}).get("burn_rate", 0):
                            violated_severity = severity

            except Exception as e:
                logger.warning(f"Error calculating burn rate for {severity} window: {e}")

        return max_burn_rate if max_burn_rate > 0 else None, violated_severity

    def evaluate_all(self, db: Session) -> List[SLOEvaluation]:
        """Evaluate all enabled SLOs.

        Args:
            db: Database session

        Returns:
            List of SLOEvaluation results
        """
        from sqlalchemy import select

        slos = db.scalars(select(SLO).where(SLO.enabled == True)).all()
        return [self.evaluate(slo) for slo in slos]

    def create_violation_ticket(
        self,
        db: Session,
        evaluation: SLOEvaluation,
    ) -> Optional[Ticket]:
        """Create a ticket for an SLO violation.

        Args:
            db: Database session
            evaluation: The SLO evaluation result

        Returns:
            Created ticket, or None if no violation or ticket already exists
        """
        if not evaluation.is_violating:
            return None

        # Check if there's already an open ticket for this SLO
        from sqlalchemy import select, and_

        existing = db.scalar(
            select(Ticket).where(
                and_(
                    Ticket.source_type == TicketSourceType.SLO_VIOLATION,
                    Ticket.source_id == str(evaluation.slo_id),
                    Ticket.status.in_([TicketStatus.PENDING, TicketStatus.IN_PROGRESS]),
                )
            )
        )

        if existing:
            logger.info(f"Ticket already exists for SLO {evaluation.slo_name} violation")
            return None

        # Determine priority from severity
        thresholds = self.DEFAULT_BURN_RATE_THRESHOLDS
        priority = thresholds.get(evaluation.violation_severity, {}).get(
            "priority", TicketPriority.MEDIUM
        )

        # Create ticket
        ticket = Ticket(
            objective=f"Investigate SLO violation: {evaluation.slo_name}",
            success_criteria=f"SLO {evaluation.slo_name} burn rate returns below threshold and error budget is recovering",
            context={
                "slo_id": evaluation.slo_id,
                "slo_name": evaluation.slo_name,
                "target": evaluation.target,
                "current_value": evaluation.current_value,
                "burn_rate": evaluation.burn_rate,
                "error_budget_remaining": evaluation.error_budget_remaining,
                "violation_severity": evaluation.violation_severity,
                "detected_at": evaluation.evaluated_at.isoformat(),
            },
            status=TicketStatus.PENDING,
            priority=priority,
            source_type=TicketSourceType.SLO_VIOLATION,
            source_id=str(evaluation.slo_id),
        )
        db.add(ticket)
        db.flush()

        # Add created event
        event = TicketEvent(
            ticket_id=ticket.id,
            event_type=TicketEventType.CREATED,
            data={
                "source": "slo_evaluator",
                "violation_severity": evaluation.violation_severity,
                "burn_rate": evaluation.burn_rate,
            },
        )
        db.add(event)
        db.commit()

        logger.info(f"Created ticket {ticket.id} for SLO {evaluation.slo_name} violation")
        return ticket
