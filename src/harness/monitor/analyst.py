"""Monitor analyst - uses Claude to analyze failures and create tickets."""

import json
import logging
from typing import Optional
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
import anthropic

from harness.config import get_settings
from harness.models import Ticket, TicketEvent, TicketStatus, TicketPriority, TicketSourceType, TicketEventType
from harness.monitor.invariant_evaluator import InvariantEvaluation
from harness.grafana import LokiClient

logger = logging.getLogger(__name__)


ANALYST_SYSTEM_PROMPT = """You are a monitor analyst for an infrastructure service harness.

Your job is to analyze invariant failures and decide:
1. Is this a real problem that needs a ticket?
2. If so, what should the ticket objective and context be?

You will receive information about:
- The failed invariant (name, query, expected condition, actual value)
- Recent logs from the system (if available)

Respond with a JSON object:
{
    "create_ticket": true/false,
    "reason": "Why or why not create a ticket",
    "objective": "What needs to be done (if creating ticket)",
    "context": "Additional context for the agent working this ticket",
    "priority": "critical/high/medium/low"
}

Guidelines:
- If a health check failed (HTTP endpoint not responding), that's usually a real problem
- If it's a transient blip that resolved, maybe don't create a ticket
- Be specific in the objective - what exactly needs to happen?
- Include useful context - what might have caused this? What should the agent check?
"""


class MonitorAnalyst:
    """Uses Claude to analyze invariant failures and create intelligent tickets."""

    def __init__(self):
        """Initialize the analyst."""
        settings = get_settings()
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._loki: Optional[LokiClient] = None

    def _get_loki(self) -> LokiClient:
        """Lazy init Loki client."""
        if self._loki is None:
            self._loki = LokiClient()
        return self._loki

    def analyze_failure(
        self,
        db: Session,
        evaluation: InvariantEvaluation,
    ) -> Optional[Ticket]:
        """Analyze an invariant failure and potentially create a ticket.

        Args:
            db: Database session
            evaluation: The failed invariant evaluation

        Returns:
            Created ticket, or None if no action needed
        """
        # Gather context
        context = self._gather_context(evaluation)

        # Build the prompt
        user_prompt = f"""An invariant check has failed. Please analyze and decide if a ticket should be created.

## Failed Invariant
- Name: {evaluation.invariant_name}
- Query: {evaluation.query}
- Expected: {evaluation.condition}
- Actual Value: {evaluation.current_value}
- Error (if any): {evaluation.error or 'None'}
- Time: {evaluation.evaluated_at.isoformat()}

## Recent Logs
{context.get('recent_logs', 'No logs available')}

Please analyze this failure and respond with a JSON object indicating whether to create a ticket and what it should contain.
"""

        try:
            # Call Claude
            response = self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                system=ANALYST_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            # Parse the response
            response_text = response.content[0].text

            # Extract JSON from response (handle markdown code blocks)
            json_text = response_text
            if "```json" in response_text:
                json_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                json_text = response_text.split("```")[1].split("```")[0]

            decision = json.loads(json_text.strip())

            logger.info(f"Analyst decision for {evaluation.invariant_name}: {decision}")

            if not decision.get("create_ticket", False):
                logger.info(f"Analyst decided not to create ticket: {decision.get('reason')}")
                return None

            # Create the ticket
            priority_map = {
                "critical": TicketPriority.CRITICAL,
                "high": TicketPriority.HIGH,
                "medium": TicketPriority.MEDIUM,
                "low": TicketPriority.LOW,
            }
            priority = priority_map.get(decision.get("priority", "high"), TicketPriority.HIGH)

            ticket = Ticket(
                objective=decision.get("objective", f"Fix: {evaluation.invariant_name}"),
                success_criteria=f"Invariant '{evaluation.invariant_name}' passes: {evaluation.condition}",
                context={
                    "invariant_id": evaluation.invariant_id,
                    "invariant_name": evaluation.invariant_name,
                    "query": evaluation.query,
                    "condition": evaluation.condition,
                    "actual_value": evaluation.current_value,
                    "analyst_context": decision.get("context", ""),
                    "analyst_reason": decision.get("reason", ""),
                    "detected_at": evaluation.evaluated_at.isoformat(),
                },
                status=TicketStatus.PENDING,
                priority=priority,
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
                    "source": "monitor_analyst",
                    "analyst_decision": decision,
                },
            )
            db.add(event)
            db.commit()

            return ticket

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse analyst response: {e}")
            # Fall back to simple ticket creation
            return self._create_simple_ticket(db, evaluation)
        except Exception as e:
            logger.exception(f"Error in analyst: {e}")
            # Fall back to simple ticket creation
            return self._create_simple_ticket(db, evaluation)

    def _gather_context(self, evaluation: InvariantEvaluation) -> dict:
        """Gather context for the analyst (logs, metrics, etc.)."""
        context = {}

        # Try to get recent logs
        try:
            loki = self._get_loki()
            # Query logs from the last 5 minutes
            result = loki.query(
                logql='{job=~".+"}',  # All jobs
                limit=20,
                start=datetime.utcnow() - timedelta(minutes=5),
                end=datetime.utcnow(),
            )

            logs = []
            for stream in result.get("data", {}).get("result", []):
                for value in stream.get("values", []):
                    logs.append(value[1])  # value[1] is the log line

            if logs:
                context["recent_logs"] = "\n".join(logs[-20:])  # Last 20 log lines
            else:
                context["recent_logs"] = "No recent logs found"

        except Exception as e:
            logger.warning(f"Failed to fetch logs for context: {e}")
            context["recent_logs"] = f"Error fetching logs: {e}"

        return context

    def _create_simple_ticket(self, db: Session, evaluation: InvariantEvaluation) -> Ticket:
        """Create a simple ticket without analyst input (fallback)."""
        ticket = Ticket(
            objective=f"Fix invariant violation: {evaluation.invariant_name}",
            success_criteria=f"Invariant '{evaluation.invariant_name}' passes: {evaluation.condition}",
            context={
                "invariant_id": evaluation.invariant_id,
                "invariant_name": evaluation.invariant_name,
                "query": evaluation.query,
                "condition": evaluation.condition,
                "actual_value": evaluation.current_value,
                "detected_at": evaluation.evaluated_at.isoformat(),
            },
            status=TicketStatus.PENDING,
            priority=TicketPriority.HIGH,
            source_type=TicketSourceType.INVARIANT_VIOLATION,
            source_id=str(evaluation.invariant_id),
        )
        db.add(ticket)
        db.flush()

        event = TicketEvent(
            ticket_id=ticket.id,
            event_type=TicketEventType.CREATED,
            data={"source": "monitor_analyst_fallback"},
        )
        db.add(event)
        db.commit()

        return ticket
