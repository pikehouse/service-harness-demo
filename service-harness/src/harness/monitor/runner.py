"""Monitor runner - the main loop for evaluating SLOs and invariants."""

import asyncio
import logging
from typing import Optional, Callable, Any
from datetime import datetime

from sqlalchemy.orm import Session

from harness.database import get_session_local
from harness.grafana import PrometheusClient
from harness.monitor.slo_evaluator import SLOEvaluator, SLOEvaluation
from harness.monitor.invariant_evaluator import InvariantEvaluator, InvariantEvaluation

logger = logging.getLogger(__name__)


class MonitorRunner:
    """Runs the monitor loop, periodically evaluating SLOs and invariants.

    The monitor is the "eyes" of the harness - it watches metrics and
    creates tickets when things go wrong.
    """

    def __init__(
        self,
        slo_interval_seconds: int = 60,
        invariant_interval_seconds: int = 60,
        prometheus_client: Optional[PrometheusClient] = None,
        session_factory: Optional[Callable[[], Session]] = None,
    ):
        """Initialize the monitor runner.

        Args:
            slo_interval_seconds: How often to evaluate SLOs (default: 60s)
            invariant_interval_seconds: How often to evaluate invariants (default: 60s)
            prometheus_client: Optional shared Prometheus client
            session_factory: Optional database session factory
        """
        self.slo_interval = slo_interval_seconds
        self.invariant_interval = invariant_interval_seconds

        self._prometheus = prometheus_client or PrometheusClient()
        self._owns_prometheus = prometheus_client is None

        self._session_factory = session_factory or get_session_local()

        self._slo_evaluator = SLOEvaluator(prometheus_client=self._prometheus)
        self._invariant_evaluator = InvariantEvaluator(prometheus_client=self._prometheus)

        self._running = False
        self._last_slo_check: Optional[datetime] = None
        self._last_invariant_check: Optional[datetime] = None

    def close(self):
        """Close resources."""
        self._slo_evaluator.close()
        self._invariant_evaluator.close()
        if self._owns_prometheus:
            self._prometheus.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def run_once(self) -> dict:
        """Run a single evaluation cycle.

        Evaluates all SLOs and invariants, creates tickets for violations.

        Returns:
            Dictionary with evaluation results
        """
        results = {
            "slo_evaluations": [],
            "invariant_evaluations": [],
            "tickets_created": [],
            "errors": [],
        }

        db = self._session_factory()
        try:
            # Evaluate SLOs
            slo_results = self._evaluate_slos(db)
            results["slo_evaluations"] = [
                {
                    "slo_id": e.slo_id,
                    "slo_name": e.slo_name,
                    "is_violating": e.is_violating,
                    "burn_rate": e.burn_rate,
                    "error_budget_remaining": e.error_budget_remaining,
                    "error": e.error,
                }
                for e in slo_results
            ]

            # Create tickets for SLO violations
            for evaluation in slo_results:
                if evaluation.is_violating:
                    ticket = self._slo_evaluator.create_violation_ticket(db, evaluation)
                    if ticket:
                        results["tickets_created"].append({
                            "ticket_id": ticket.id,
                            "type": "slo_violation",
                            "source": evaluation.slo_name,
                        })

            # Evaluate invariants
            invariant_results = self._evaluate_invariants(db)
            results["invariant_evaluations"] = [
                {
                    "invariant_id": e.invariant_id,
                    "invariant_name": e.invariant_name,
                    "is_passing": e.is_passing,
                    "current_value": e.current_value,
                    "threshold_value": e.threshold_value,
                    "error": e.error,
                }
                for e in invariant_results
            ]

            # Create tickets for invariant violations
            for evaluation in invariant_results:
                if not evaluation.is_passing:
                    ticket = self._invariant_evaluator.create_violation_ticket(db, evaluation)
                    if ticket:
                        results["tickets_created"].append({
                            "ticket_id": ticket.id,
                            "type": "invariant_violation",
                            "source": evaluation.invariant_name,
                        })

            self._last_slo_check = datetime.utcnow()
            self._last_invariant_check = datetime.utcnow()

        except Exception as e:
            logger.exception("Error in monitor run_once")
            results["errors"].append(str(e))
        finally:
            db.close()

        return results

    def _evaluate_slos(self, db: Session) -> list:
        """Evaluate all enabled SLOs."""
        try:
            return self._slo_evaluator.evaluate_all(db)
        except Exception as e:
            logger.exception("Error evaluating SLOs")
            return []

    def _evaluate_invariants(self, db: Session) -> list:
        """Evaluate all enabled invariants."""
        try:
            return self._invariant_evaluator.evaluate_all(db)
        except Exception as e:
            logger.exception("Error evaluating invariants")
            return []

    async def run_async(self):
        """Run the monitor loop asynchronously.

        This runs forever, evaluating SLOs and invariants at their
        configured intervals.
        """
        self._running = True
        logger.info(
            f"Starting monitor loop (SLO interval: {self.slo_interval}s, "
            f"invariant interval: {self.invariant_interval}s)"
        )

        # Use the smaller interval as our tick rate
        tick_interval = min(self.slo_interval, self.invariant_interval)

        while self._running:
            now = datetime.utcnow()
            db = self._session_factory()

            try:
                # Check if it's time to evaluate SLOs
                if self._should_check_slos(now):
                    logger.debug("Evaluating SLOs...")
                    slo_results = self._evaluate_slos(db)
                    for evaluation in slo_results:
                        if evaluation.is_violating:
                            self._slo_evaluator.create_violation_ticket(db, evaluation)
                    self._last_slo_check = now

                # Check if it's time to evaluate invariants
                if self._should_check_invariants(now):
                    logger.debug("Evaluating invariants...")
                    invariant_results = self._evaluate_invariants(db)
                    for evaluation in invariant_results:
                        if not evaluation.is_passing:
                            self._invariant_evaluator.create_violation_ticket(db, evaluation)
                    self._last_invariant_check = now

            except Exception as e:
                logger.exception("Error in monitor loop iteration")
            finally:
                db.close()

            await asyncio.sleep(tick_interval)

    def _should_check_slos(self, now: datetime) -> bool:
        """Check if enough time has passed to evaluate SLOs."""
        if self._last_slo_check is None:
            return True
        elapsed = (now - self._last_slo_check).total_seconds()
        return elapsed >= self.slo_interval

    def _should_check_invariants(self, now: datetime) -> bool:
        """Check if enough time has passed to evaluate invariants."""
        if self._last_invariant_check is None:
            return True
        elapsed = (now - self._last_invariant_check).total_seconds()
        return elapsed >= self.invariant_interval

    def stop(self):
        """Stop the monitor loop."""
        logger.info("Stopping monitor loop")
        self._running = False

    def run(self):
        """Run the monitor loop synchronously (blocking).

        This is a convenience method that runs the async loop in
        the current thread.
        """
        asyncio.run(self.run_async())

    @property
    def status(self) -> dict:
        """Get the current monitor status."""
        return {
            "running": self._running,
            "last_slo_check": self._last_slo_check.isoformat() if self._last_slo_check else None,
            "last_invariant_check": self._last_invariant_check.isoformat() if self._last_invariant_check else None,
            "slo_interval_seconds": self.slo_interval,
            "invariant_interval_seconds": self.invariant_interval,
        }
