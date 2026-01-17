# Demo Loop Design: Autonomous Service Recovery

## Overview

Build the entry points and scheduling needed to run the full harness loop. The demo: start the harness, kill the rate limiter, watch the system detect the failure and recover automatically.

## Demo Flow

```
harness run
    ├── web (FastAPI on :8000)
    ├── monitor (checks every 5s)
    ├── agent (polls for tickets)
    └── service (rate limiter on :8001)

Kill the service process
    ↓
Monitor health check fails (deterministic)
    ↓
Monitor invokes Claude analyst: "What's wrong? Should I create a ticket?"
    ↓
Claude: "Rate limiter is down. Create ticket to restart it."
    ↓
Ticket created with intelligent context
    ↓
Agent picks up ticket, marks in_progress
    ↓
Agent (via Claude) investigates, runs restart command, verifies
    ↓
Ticket marked completed
```

## Architecture

### Process Model

Single supervisor process spawns 4 subprocesses:
- **web** - FastAPI server on port 8000
- **monitor** - Health checks + analyst agent
- **agent** - Ticket worker
- **service** - Rate limiter on port 8001

Supervisor behavior:
- Spawns all processes on startup
- Logs stdout/stderr from each
- Graceful shutdown on SIGINT/SIGTERM
- Does NOT auto-restart crashed processes (agent handles recovery)

### Monitor

**Components:**

1. **Scheduler** - Runs checks every 5 seconds

2. **Health checker** - Deterministic HTTP calls to configured endpoints (invariants with `http://` query prefix)

3. **Analyst agent** - When checks fail, invokes Claude with:
   - What failed (health check details)
   - Recent logs from Loki
   - Recent metrics from Prometheus
   - Current invariant config

   Claude decides whether to create a ticket and crafts the objective/context/priority.

**Deduplication:**
- Before creating ticket, check for existing open ticket for same invariant
- Query: `source_type='invariant' AND source_id={id} AND status IN ('pending', 'in_progress')`
- If exists: skip or add note to existing
- If not: create new ticket

**Invariant config for health checks:**
```python
Invariant(
    name="rate_limiter_healthy",
    description="Rate limiter service responds to health checks",
    query="http://localhost:8001/health",  # http:// prefix = health check
    condition="status == 200",
    enabled=True,
)
```

### Agent

**Loop:**
```python
while running:
    ticket = get_next_ready_ticket()  # pending + deps met
    if ticket:
        mark_in_progress(ticket)  # lock it
        work_ticket(ticket)
    else:
        sleep(5)
```

**Working a ticket:**
1. Build context from ticket (objective, criteria, events)
2. Call Claude with tools
3. Loop until Claude completes or gives up
4. Update ticket status
5. Record trajectory

**Available tools:**
- `query_metrics` - Prometheus
- `query_logs` - Loki
- `read_file`, `list_files`, `search_code` - Codebase
- `run_command` - Shell execution (restart service, etc.)
- `add_ticket_note` - Record observations
- `update_ticket_status` - Complete/fail ticket

### CLI

```
harness run      # supervisor with all processes
harness web      # just web server
harness monitor  # just monitor
harness agent    # just agent
harness service  # just rate limiter
```

## New Files

- `src/harness/cli.py` - Click/argparse CLI entry point
- `src/harness/supervisor.py` - Process spawning and management
- `src/harness/monitor/scheduler.py` - Interval-based check runner
- `src/harness/monitor/analyst.py` - LLM-powered failure analysis

## Modified Files

- `pyproject.toml` - Add `[project.scripts]` for CLI
- `src/harness/monitor/runner.py` - Wire to scheduler
- `src/harness/monitor/invariant_evaluator.py` - Add HTTP health check support
- `src/harness/agent/runner.py` - Add polling loop, ticket locking
- `src/harness/service/rate_limiter.py` - Add `__main__` for standalone run

## Configuration

Health check invariant (seed data or via API):
```json
{
    "name": "rate_limiter_healthy",
    "description": "Rate limiter responds to health checks",
    "query": "http://localhost:8001/health",
    "condition": "status == 200",
    "enabled": true
}
```

## Success Criteria

Demo succeeds when:
1. `harness run` starts all 4 processes
2. Kill rate limiter subprocess manually
3. Within 10 seconds: ticket appears
4. Within 60 seconds: agent restarts service, closes ticket
5. Health check passes again
