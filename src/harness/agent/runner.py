"""Agent runner - the main loop for working tickets with Claude."""

from typing import Optional, Dict, Any, List, Callable
from datetime import datetime
import logging
import json

from anthropic import Anthropic
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from harness.config import get_settings
from harness.models import Ticket, TicketEvent, TicketStatus, TicketEventType
from harness.agent.tools import AgentToolkit

logger = logging.getLogger(__name__)

# ANSI color codes
COLORS = {
    "green": "\033[32m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
    "red": "\033[31m",
    "magenta": "\033[35m",
    "bold": "\033[1m",
    "reset": "\033[0m",
}


class AgentRunner:
    """Runs the agent loop, working tickets by calling Claude with tools.

    The agent is the "hands" of the harness - it picks up ready tickets,
    uses Claude to analyze and solve problems, and takes action.
    """

    DEFAULT_SYSTEM_PROMPT = """You are an AI agent responsible for maintaining infrastructure services.

## IMPORTANT: Be Direct and Fast
Don't waste time exploring. If a health check is failing, restart the service immediately.

## Service Commands (use run_command tool):
- Restart rate limiter: nohup harness service > /dev/null 2>&1 &
- Check health: curl -s http://localhost:8001/health

## Workflow for Health Check Failures:
1. Service is down? Run: nohup harness service > /dev/null 2>&1 &
2. Wait a moment, then verify: curl -s http://localhost:8001/health
3. If health returns {"status": "healthy"}, use update_ticket_status to mark as completed

Don't read code. Don't query logs. Just restart and verify."""

    def __init__(
        self,
        session_factory: Optional[Callable[[], Session]] = None,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        max_turns: int = 10,
        workspace_path: Optional[str] = None,
    ):
        """Initialize the agent runner.

        Args:
            session_factory: Database session factory
            api_key: Anthropic API key (defaults to settings)
            model: Claude model to use
            max_turns: Maximum conversation turns per ticket
            workspace_path: Path to the service workspace
        """
        settings = get_settings()
        self._api_key = api_key or settings.anthropic_api_key

        if not self._api_key:
            raise ValueError("Anthropic API key is required")

        self._client = Anthropic(api_key=self._api_key)
        self._model = model
        self._max_turns = max_turns
        self._workspace_path = workspace_path

        from harness.database import get_session_local
        self._session_factory = session_factory or get_session_local()

    def get_ready_tickets(self, db: Session) -> List[Ticket]:
        """Get tickets that are ready to be worked.

        A ticket is ready when:
        - Status is PENDING
        - All dependencies are COMPLETED
        """
        # Get all pending tickets
        query = select(Ticket).where(Ticket.status == TicketStatus.PENDING)
        pending = list(db.scalars(query).all())

        # Filter to only ready tickets
        ready = [t for t in pending if t.is_ready()]

        # Sort by priority (critical first) then by created_at
        priority_order = {
            "critical": 0,
            "high": 1,
            "medium": 2,
            "low": 3,
        }
        ready.sort(key=lambda t: (priority_order.get(t.priority.value, 2), t.created_at))

        return ready

    def work_ticket(self, ticket: Ticket, db: Session) -> Dict[str, Any]:
        """Work a single ticket using Claude.

        Args:
            ticket: The ticket to work
            db: Database session

        Returns:
            Result dict with trajectory and outcome
        """
        logger.info(f"Starting work on ticket {ticket.id}: {ticket.objective}")
        c = COLORS
        print(f"\n{c['bold']}{c['green']}▶ WORKING TICKET #{ticket.id}{c['reset']}", flush=True)
        print(f"  {c['cyan']}Objective:{c['reset']} {ticket.objective}", flush=True)

        # Mark as in progress
        ticket.status = TicketStatus.IN_PROGRESS
        db.add(TicketEvent(
            ticket_id=ticket.id,
            event_type=TicketEventType.STATUS_CHANGED,
            data={"old_status": "pending", "new_status": "in_progress", "source": "agent"},
        ))
        db.commit()

        # Initialize toolkit
        toolkit = AgentToolkit(
            db=db,
            workspace_path=self._workspace_path,
        )

        # Build initial context
        messages = self._build_initial_messages(ticket)
        tools = toolkit.get_tool_definitions()

        # Trajectory for training data
        trajectory = {
            "ticket_id": ticket.id,
            "objective": ticket.objective,
            "started_at": datetime.utcnow().isoformat(),
            "steps": [],
        }

        # Agent loop
        turn = 0
        final_status = None

        while turn < self._max_turns:
            turn += 1
            logger.debug(f"Ticket {ticket.id}: Turn {turn}")
            print(f"  {COLORS['yellow']}Turn {turn}/{self._max_turns}{COLORS['reset']}", flush=True)

            try:
                # Call Claude
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=4096,
                    system=self.DEFAULT_SYSTEM_PROMPT,
                    tools=tools,
                    messages=messages,
                )

                # Record step
                step = {
                    "turn": turn,
                    "timestamp": datetime.utcnow().isoformat(),
                    "response": {
                        "stop_reason": response.stop_reason,
                        "content": [self._content_to_dict(c) for c in response.content],
                    },
                }

                # Process response
                if response.stop_reason == "end_turn":
                    # Claude finished without tool use - extract final message
                    final_message = self._extract_text_content(response.content)
                    step["action"] = "completed"
                    trajectory["steps"].append(step)

                    # Check if Claude indicated success or failure
                    if any(word in final_message.lower() for word in ["completed", "fixed", "resolved", "success"]):
                        final_status = "completed"
                    elif any(word in final_message.lower() for word in ["blocked", "cannot", "unable", "need help"]):
                        final_status = "blocked"
                    else:
                        final_status = "completed"  # Default to completed if no tool use

                    break

                elif response.stop_reason == "tool_use":
                    # Claude wants to use tools
                    tool_results = []

                    for content in response.content:
                        if content.type == "tool_use":
                            tool_name = content.name
                            tool_input = content.input

                            logger.debug(f"Executing tool: {tool_name}")
                            print(f"    {COLORS['magenta']}→ {tool_name}{COLORS['reset']}({', '.join(f'{k}={repr(v)[:50]}' for k, v in tool_input.items())})", flush=True)
                            result = toolkit.execute_tool(tool_name, tool_input)

                            # Record agent action event
                            db.add(TicketEvent(
                                ticket_id=ticket.id,
                                event_type=TicketEventType.AGENT_ACTION,
                                data={
                                    "tool": tool_name,
                                    "input": tool_input,
                                    "success": result["success"],
                                    "turn": turn,
                                },
                            ))

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": content.id,
                                "content": json.dumps(result),
                            })

                    step["tool_calls"] = [
                        {"tool": c.name, "input": c.input}
                        for c in response.content if c.type == "tool_use"
                    ]
                    step["tool_results"] = tool_results
                    trajectory["steps"].append(step)

                    # Add assistant response and tool results to messages
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({"role": "user", "content": tool_results})

                    db.commit()

                else:
                    # Unexpected stop reason
                    logger.warning(f"Unexpected stop reason: {response.stop_reason}")
                    step["action"] = f"unexpected_stop_{response.stop_reason}"
                    trajectory["steps"].append(step)
                    final_status = "failed"
                    break

            except Exception as e:
                logger.exception(f"Error in agent loop for ticket {ticket.id}")
                step = {
                    "turn": turn,
                    "timestamp": datetime.utcnow().isoformat(),
                    "error": str(e),
                }
                trajectory["steps"].append(step)
                final_status = "failed"
                break

        # If we hit max turns without finishing
        if turn >= self._max_turns and final_status is None:
            final_status = "failed"
            trajectory["steps"].append({
                "turn": turn,
                "timestamp": datetime.utcnow().isoformat(),
                "action": "max_turns_exceeded",
            })

        # Update ticket status
        trajectory["ended_at"] = datetime.utcnow().isoformat()
        trajectory["final_status"] = final_status
        trajectory["turns_used"] = turn

        if final_status:
            status_map = {
                "completed": TicketStatus.COMPLETED,
                "failed": TicketStatus.FAILED,
                "blocked": TicketStatus.BLOCKED,
            }
            ticket.status = status_map.get(final_status, TicketStatus.FAILED)
            if final_status in ["completed", "failed"]:
                ticket.resolved_at = datetime.utcnow()

            db.add(TicketEvent(
                ticket_id=ticket.id,
                event_type=TicketEventType.STATUS_CHANGED,
                data={
                    "old_status": "in_progress",
                    "new_status": final_status,
                    "source": "agent",
                    "turns_used": turn,
                },
            ))
            db.commit()

        logger.info(f"Finished ticket {ticket.id} with status: {final_status}")

        return trajectory

    def _build_initial_messages(self, ticket: Ticket) -> List[Dict[str, Any]]:
        """Build the initial messages for the conversation."""
        context_str = ""
        if ticket.context:
            context_str = f"\n\nAdditional context:\n{json.dumps(ticket.context, indent=2)}"

        user_message = f"""Please work on this ticket:

**Objective:** {ticket.objective}

**Success Criteria:** {ticket.success_criteria or 'Not specified - use your judgment'}

**Priority:** {ticket.priority.value}

**Source:** {ticket.source_type.value}
{context_str}

Please investigate and resolve this issue. Use the available tools to gather information and take action.
Start by understanding the current state, then proceed to diagnose and fix the issue.
Update the ticket status when you're done."""

        return [{"role": "user", "content": user_message}]

    def _extract_text_content(self, content: List) -> str:
        """Extract text from response content."""
        texts = []
        for c in content:
            if hasattr(c, "text"):
                texts.append(c.text)
        return "\n".join(texts)

    def _content_to_dict(self, content) -> Dict[str, Any]:
        """Convert content block to dict for JSON serialization."""
        if hasattr(content, "text"):
            return {"type": "text", "text": content.text}
        elif hasattr(content, "name"):
            return {"type": "tool_use", "name": content.name, "input": content.input}
        else:
            return {"type": str(type(content))}

    def run_once(self) -> Dict[str, Any]:
        """Run one iteration of the agent.

        Picks the highest priority ready ticket and works it.

        Returns:
            Result dict with trajectory or None if no work
        """
        db = self._session_factory()
        try:
            ready_tickets = self.get_ready_tickets(db)

            if not ready_tickets:
                logger.debug("No ready tickets to work")
                return {"status": "no_work", "message": "No ready tickets"}

            # Work the highest priority ticket
            ticket = ready_tickets[0]
            trajectory = self.work_ticket(ticket, db)

            return {
                "status": "worked",
                "ticket_id": ticket.id,
                "trajectory": trajectory,
            }
        finally:
            db.close()

    def run(self, poll_interval: float = 5.0):
        """Run the agent loop synchronously.

        Args:
            poll_interval: Seconds between checking for ready tickets
        """
        import time
        import signal

        self._running = True

        def handle_signal(signum, frame):
            logger.info("Agent received shutdown signal")
            self._running = False

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        logger.info(f"Starting agent loop (poll interval: {poll_interval}s)")
        print(f"{COLORS['bold']}{COLORS['green']}🤖 Agent running{COLORS['reset']} (polling every {poll_interval}s)", flush=True)

        while self._running:
            try:
                result = self.run_once()
                if result["status"] == "worked":
                    logger.info(f"Completed ticket {result['ticket_id']}")
                    status = result['trajectory']['final_status']
                    status_color = COLORS['green'] if status == 'completed' else COLORS['red']
                    print(f"\n{COLORS['bold']}✓ TICKET #{result['ticket_id']} → {status_color}{status.upper()}{COLORS['reset']}\n", flush=True)
                elif result["status"] == "no_work":
                    pass  # Silent when no work
                else:
                    print(f"{COLORS['yellow']}Agent: {result}{COLORS['reset']}", flush=True)
            except Exception as e:
                logger.exception("Error in agent loop")
                print(f"{COLORS['red']}Agent error: {e}{COLORS['reset']}", flush=True)
                import traceback
                traceback.print_exc()

            # Sleep in small increments to allow shutdown
            sleep_remaining = poll_interval
            while sleep_remaining > 0 and self._running:
                time.sleep(min(0.5, sleep_remaining))
                sleep_remaining -= 0.5

        logger.info("Agent stopped")

    async def run_async(self, poll_interval: int = 30):
        """Run the agent loop asynchronously.

        Args:
            poll_interval: Seconds between checking for ready tickets
        """
        import asyncio

        logger.info(f"Starting agent loop (poll interval: {poll_interval}s)")

        while True:
            try:
                result = self.run_once()
                if result["status"] == "worked":
                    logger.info(f"Completed ticket {result['ticket_id']}")
                else:
                    logger.debug("No work, sleeping...")
            except Exception as e:
                logger.exception("Error in agent loop")

            await asyncio.sleep(poll_interval)
