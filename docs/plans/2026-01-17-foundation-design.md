# Foundation Design: AI-Native Infrastructure Harness

## Overview

Build the foundation layer of the harness: database schema, basic web API, and Grafana Cloud integration. This establishes the core data model before building the monitor and agent processes.

## Technology Stack

- **Language:** Python 3
- **Web Framework:** FastAPI
- **Database:** SQLite with SQLAlchemy ORM
- **Metrics/Logs:** Grafana Cloud (Prometheus + Loki)
- **Testing:** pytest

## Data Model

### Core Entities

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│     Ticket      │     │       SLO       │     │    Invariant    │
├─────────────────┤     ├─────────────────┤     ├─────────────────┤
│ id              │     │ id              │     │ id              │
│ objective       │     │ name            │     │ name            │
│ success_criteria│     │ description     │     │ description     │
│ context (JSON)  │     │ target          │     │ query           │
│ status          │     │ window_days     │     │ condition       │
│ priority        │     │ metric_query    │     │ enabled         │
│ source_type     │     │ burn_rate_      │     │ created_at      │
│ source_id       │     │   thresholds    │     │ updated_at      │
│ created_at      │     │ enabled         │     └─────────────────┘
│ updated_at      │     │ created_at      │
│ resolved_at     │     │ updated_at      │
└─────────────────┘     └─────────────────┘
        │
        │ 1:many
        ▼
┌─────────────────┐     ┌─────────────────────┐
│  TicketEvent    │     │  TicketDependency   │
├─────────────────┤     ├─────────────────────┤
│ id              │     │ ticket_id      (FK) │
│ ticket_id  (FK) │     │ depends_on_id  (FK) │
│ event_type      │     │ created_at          │
│ data (JSON)     │     └─────────────────────┘
│ created_at      │
└─────────────────┘
```

### Key Decisions

- **TicketEvent**: Append-only log capturing all ticket history (status changes, agent actions, notes). Becomes the trajectory for training.
- **TicketDependency**: Many-to-many relationship. A ticket can depend on multiple others.
- **source_type/source_id**: Links ticket to what created it (SLO violation, invariant failure, human, webhook).
- **JSON fields**: For flexible data (context, criteria, thresholds). SQLite handles this fine.

### Ticket Status Values

- `pending` - Not yet started
- `in_progress` - Agent is working on it
- `completed` - Successfully resolved
- `failed` - Could not be resolved
- `blocked` - Waiting on external action (human approval, etc.)

### "Ready" Tickets

A ticket is "ready" when:
- Status is `pending`
- AND (no dependencies OR all dependencies have status `completed`)

## Project Structure

```
service-harness/
├── src/
│   └── harness/
│       ├── __init__.py
│       ├── config.py          # Pydantic settings, loads .env
│       ├── database.py        # SQLite connection, migrations
│       ├── models.py          # SQLAlchemy models
│       ├── schemas.py         # Pydantic schemas for API
│       ├── grafana/
│       │   ├── __init__.py
│       │   ├── prometheus.py  # Push/query metrics
│       │   └── loki.py        # Push/query logs
│       └── web/
│           ├── __init__.py
│           ├── app.py         # FastAPI app
│           └── routes/
│               ├── tickets.py
│               ├── slos.py
│               └── invariants.py
├── tests/
│   ├── conftest.py            # Fixtures (test DB, test client)
│   ├── test_models.py
│   ├── test_api_tickets.py
│   ├── test_api_slos.py
│   └── test_grafana.py
├── .env                       # Credentials (gitignored)
├── .env.example               # Template
├── pyproject.toml             # Dependencies, pytest config
└── README.md
```

## API Design

### Tickets

```
GET    /api/tickets                    # List (filterable by status, source_type)
GET    /api/tickets?status=ready       # Ready tickets (pending + deps completed)
POST   /api/tickets                    # Create (human-initiated)
GET    /api/tickets/{id}               # Get with events
PATCH  /api/tickets/{id}               # Update status, add context
GET    /api/tickets/{id}/events        # Event history (trajectory)
POST   /api/tickets/{id}/events        # Add event
POST   /api/tickets/{id}/dependencies  # Add dependency
DELETE /api/tickets/{id}/dependencies/{dep_id}  # Remove dependency
GET    /api/tickets/{id}/dependencies  # List dependencies
```

### SLOs

```
GET    /api/slos                 # List all
POST   /api/slos                 # Create
GET    /api/slos/{id}            # Get with current burn rate
PATCH  /api/slos/{id}            # Update
DELETE /api/slos/{id}            # Soft delete (disable)
```

### Invariants

```
GET    /api/invariants           # List all
POST   /api/invariants           # Create
GET    /api/invariants/{id}      # Get with last check result
PATCH  /api/invariants/{id}      # Update
DELETE /api/invariants/{id}      # Soft delete (disable)
```

### Health/Meta

```
GET    /health                   # Basic health check
GET    /api/stats                # Dashboard summary
```

### API Notes

- No auth for now (local dev)
- All responses JSON with standard error format
- Pagination via `?limit=` and `?offset=` on list endpoints

## Grafana Cloud Configuration

| Service | URL | Username |
|---------|-----|----------|
| Prometheus | `https://prometheus-prod-67-prod-us-west-0.grafana.net/api/prom/push` | `2920261` |
| Loki | `https://logs-prod-021.grafana.net` | `1455803` |

Same API token for both services (stored in `.env`).

## Success Criteria

Foundation is complete when:

1. All models created with proper relationships
2. All API endpoints implemented and tested
3. Grafana client can push and query metrics/logs
4. Tests pass with >80% coverage on core modules
5. Can create a ticket, add dependencies, query ready tickets
