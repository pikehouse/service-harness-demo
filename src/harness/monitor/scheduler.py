"""Monitor scheduler - runs health checks on an interval."""

import time
import signal
import logging
from typing import List

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from harness.database import get_session
from harness.models import Invariant, Ticket, TicketStatus
from harness.monitor.invariant_evaluator import InvariantEvaluator, InvariantEvaluation
from harness.monitor.analyst import MonitorAnalyst

logger = logging.getLogger(__name__)


class MonitorScheduler:
    """Runs invariant checks on a fixed interval.

    When checks fail, invokes the analyst agent to decide whether
    to create a ticket and what context to include.
    """

    def __init__(self, interval_seconds: float = 5.0):
        """Initialize the scheduler.

        Args:
            interval_seconds: How often to run checks (default 5s)
        """
        self.interval = interval_seconds
        self.running = False
        self._evaluator = None
        self._analyst = None

    def run(self):
        """Run the scheduler loop."""
        self.running = True

        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        self._evaluator = InvariantEvaluator()
        self._analyst = MonitorAnalyst()

        logger.info(f"Monitor scheduler starting (interval={self.interval}s)")
        print(f"Monitor scheduler running (checking every {self.interval}s)")

        try:
            while self.running:
                try:
                    self._run_checks()
                except Exception as e:
                    logger.exception(f"Error in monitor check cycle: {e}")
                    print(f"Monitor error: {e}")

                # Sleep in small increments to allow shutdown
                sleep_remaining = self.interval
                while sleep_remaining > 0 and self.running:
                    time.sleep(min(0.5, sleep_remaining))
                    sleep_remaining -= 0.5

        finally:
            if self._evaluator:
                self._evaluator.close()
            logger.info("Monitor scheduler stopped")

    def _handle_signal(self, signum, frame):
        """Handle shutdown signals."""
        logger.info("Monitor scheduler received shutdown signal")
        self.running = False

    def _run_checks(self):
        """Run all invariant checks."""
        with get_session() as db:
            # Get all enabled invariants
            invariants = db.scalars(
                select(Invariant).where(Invariant.enabled == True)
            ).all()

            if not invariants:
                return

            # Evaluate each invariant
            failures: List[InvariantEvaluation] = []

            for invariant in invariants:
                evaluation = self._evaluator.evaluate(invariant)

                if not evaluation.is_passing:
                    logger.warning(
                        f"Invariant '{evaluation.invariant_name}' FAILED: "
                        f"value={evaluation.current_value}, condition={evaluation.condition}"
                    )
                    print(
                        f"ALERT: Invariant '{evaluation.invariant_name}' failed "
                        f"(value={evaluation.current_value})"
                    )
                    failures.append(evaluation)
                else:
                    logger.debug(f"Invariant '{evaluation.invariant_name}' passed")

            # If there are failures, invoke the analyst
            if failures:
                self._handle_failures(db, failures)

    def _handle_failures(self, db: Session, failures: List[InvariantEvaluation]):
        """Handle failed invariant checks by invoking the analyst.

        Args:
            db: Database session
            failures: List of failed evaluations
        """
        for evaluation in failures:
            # Check if there's already an open ticket for this invariant
            existing = db.scalar(
                select(Ticket).where(
                    and_(
                        Ticket.source_id == str(evaluation.invariant_id),
                        Ticket.status.in_([TicketStatus.PENDING, TicketStatus.IN_PROGRESS]),
                    )
                )
            )

            if existing:
                logger.info(
                    f"Ticket {existing.id} already exists for invariant "
                    f"'{evaluation.invariant_name}', skipping"
                )
                continue

            # Invoke the analyst to decide what to do
            print(f"Analyzing failure: {evaluation.invariant_name}...")
            ticket = self._analyst.analyze_failure(db, evaluation)

            if ticket:
                print(f"Created ticket #{ticket.id}: {ticket.objective}")
                logger.info(f"Created ticket {ticket.id} for invariant failure")
