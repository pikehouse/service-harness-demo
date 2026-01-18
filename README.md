# Harness

AI-native infrastructure management system. Harness enables AI agents to monitor, maintain, and improve infrastructure services through a structured workflow with observability, ticketing, and deployment automation.

## Features

- **Web Dashboard**: Real-time view of tickets, invariants, and actions
- **AI Agent Loop**: Claude-powered agent with tools for investigation and remediation
- **Observability Integration**: Query Prometheus metrics and Loki logs
- **Invariant System**: Define and monitor system constraints
- **Subject Management**: Manage multiple infrastructure services
- **Action Logging**: Full audit trail of all agent actions

## Quick Start

### Prerequisites

- Python 3.10+
- Anthropic API key (for agent)
- Optional: Grafana Cloud account (for metrics/logs)

### Installation

```bash
# Clone the repository
cd harness

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install the package
pip install -e .

# Install dev dependencies
pip install -e ".[dev]"
```

### Configuration

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your credentials
# At minimum, set ANTHROPIC_API_KEY for the agent
```

### Initialize Database

```bash
python -m harness init
```

### Start the Dashboard

```bash
python -m harness web
# Open http://localhost:8000
```

### Start the Agent

```bash
python -m harness agent

# Or work on a specific subject
python -m harness agent --subject ratelimiter

# Or work on a specific ticket
python -m harness agent --ticket 1
```

### Start Rate Limiter Subject

```bash
cd subjects/ratelimiter
pip install -e .
python -m ratelimiter.main
# Service runs on http://localhost:8001
```

## Project Structure

```
harness/
├── src/                      # Main harness package
│   ├── main.py              # CLI entry points
│   ├── config.py            # Configuration management
│   ├── db.py                # Database setup
│   ├── models/              # SQLAlchemy models
│   │   ├── ticket.py        # Ticket model
│   │   ├── invariant.py     # Invariant model
│   │   └── action.py        # Action log model
│   ├── web/                 # FastAPI dashboard
│   │   ├── app.py           # Main app
│   │   ├── routers/         # API routes
│   │   └── templates/       # Jinja2 templates
│   ├── observability/       # Metrics & logs clients
│   │   ├── prometheus.py    # PromQL queries
│   │   └── loki.py          # LogQL queries
│   ├── agent_loop/          # AI agent
│   │   ├── loop.py          # Main agent loop
│   │   ├── claude.py        # Claude API client
│   │   ├── tools.py         # Tool definitions
│   │   ├── display.py       # Rich terminal output
│   │   └── handlers/        # Tool implementations
│   └── invariants/          # Constraint evaluation
│       └── evaluator.py     # Invariant checker
├── subjects/                 # Managed services
│   └── ratelimiter/         # Rate limiter service
│       ├── src/
│       │   ├── bucket.py    # Token bucket algorithm
│       │   ├── app.py       # FastAPI endpoints
│       │   └── metrics.py   # Prometheus metrics
│       └── tests/
├── scripts/
│   ├── deploy.sh            # Deployment script
│   └── simulate_traffic.py  # Traffic generator
├── data/                     # SQLite database
├── AGENTS.md                # AI agent guide
└── README.md                # This file
```

## Usage

### Dashboard

The web dashboard at `http://localhost:8000` shows:
- Open tickets and their status
- Active invariants and violations
- Recent agent actions

### Agent Commands

In the agent loop, you can:
- Describe problems for investigation
- Ask for specific metrics or logs
- Request code changes
- Direct deployment actions

Example session:
```
You: Check the rate limiter rejection rate
Agent: [Queries Prometheus, shows results]

You: Why is it high?
Agent: [Queries logs, searches code, explains]

You: Fix it by increasing the capacity
Agent: [Edits config, runs tests, deploys]
```

### Invariants

Create invariants via API:
```bash
curl -X POST http://localhost:8000/api/invariants \
  -H "Content-Type: application/json" \
  -d '{
    "name": "api_error_rate",
    "subject": "ratelimiter",
    "promql_query": "rate(http_errors_total[5m])",
    "threshold": 0.01,
    "operator": "<"
  }'
```

### Traffic Simulation

Test the rate limiter with simulated traffic:
```bash
python scripts/simulate_traffic.py --rps 20 --duration 60

# With bursts
python scripts/simulate_traffic.py --rps 20 --duration 60 --burst 2.0
```

## Development

### Running Tests

```bash
# Rate limiter tests
cd subjects/ratelimiter
pytest tests/ -v

# All tests
pytest
```

### Adding a New Subject

1. Create directory: `subjects/<name>/`
2. Add `pyproject.toml` with dependencies
3. Create `src/` with:
   - `app.py` - FastAPI application
   - `metrics.py` - Prometheus metrics
4. Add `tests/` directory
5. Create `AGENTS.md` with subject-specific guidance

## Architecture

### Data Flow

```
User/Schedule → Agent Loop → Tools → Handlers → Services/DB
                    ↓
              Claude API
                    ↓
            Observability ← Prometheus/Loki
```

### Key Design Decisions

- **SQLite**: Simple, file-based persistence
- **FastAPI**: Modern async Python web framework
- **Rich**: Beautiful terminal output for agent
- **Prometheus**: Standard metrics format
- **Structured Tools**: Clear boundaries for AI actions

## License

MIT
