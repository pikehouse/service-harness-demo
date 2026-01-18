# AI-Native Infrastructure Harness

> **Background:** Read the [AI-Native Infrastructure Harness Primer](https://claude.ai/public/artifacts/075cc351-1198-4af5-b761-a5c27f5acb38) for the full vision behind this project.

An autonomous infrastructure management system where AI agents monitor, diagnose, and fix production services in real-time.

## What is this?

This harness demonstrates a new paradigm: **AI operates the infrastructure, not inside it**. The service itself stays deterministic and testable. The AI agent watches from outside, detects problems, and fixes them autonomously.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         THE HARNESS                                 │
│                                                                     │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐            │
│   │   SERVICE   │    │   MONITOR   │    │    AGENT    │            │
│   │             │    │             │    │             │            │
│   │ Rate limit  │◄───│ Watches for │───►│ Claude AI   │            │
│   │ service on  │    │ SLO viola-  │    │ diagnoses & │            │
│   │ port 8001   │    │ tions every │    │ fixes issues│            │
│   │             │    │ 5 seconds   │    │ autonomously│            │
│   └─────────────┘    └─────────────┘    └─────────────┘            │
│         │                   │                  │                    │
│         │                   ▼                  │                    │
│         │           ┌─────────────┐            │                    │
│         │           │   TICKETS   │◄───────────┘                    │
│         │           │  Database   │                                 │
│         │           └─────────────┘                                 │
│         │                                                           │
│         ▼                                                           │
│   ┌─────────────────────────────────────────┐                      │
│   │           service_config.json           │                      │
│   │  {"enabled": true, "delay_ms": 0}       │  ◄── Agent edits     │
│   └─────────────────────────────────────────┘      this to fix     │
│                                                    problems        │
└─────────────────────────────────────────────────────────────────────┘
```

## The Demo

The demo shows autonomous recovery in action:

1. **You break the service** (press a key to inject a fault)
2. **Monitor detects the SLO violation** (health check fails or latency spikes)
3. **Agent diagnoses the problem** (reads code, config, runs commands)
4. **Agent fixes it** (edits the config file)
5. **Service recovers** (automatically, no human intervention)

```
┌───────────────────────────────────────────────────────────────────┐
│                        DEMO FLOW                                  │
│                                                                   │
│  You press 'Z'          Monitor detects         Agent fixes it   │
│       │                      │                       │            │
│       ▼                      ▼                       ▼            │
│  ┌─────────┐           ┌──────────┐           ┌──────────┐       │
│  │ Inject  │           │ Latency  │           │ Edit     │       │
│  │ 500ms   │──────────►│ > 200ms! │──────────►│ config   │       │
│  │ delay   │           │ Create   │           │ delay=0  │       │
│  └─────────┘           │ ticket   │           └──────────┘       │
│                        └──────────┘                  │            │
│                                                      ▼            │
│                                                ┌──────────┐       │
│                                                │ Verify   │       │
│                                                │ health   │       │
│                                                │ ✓ Fixed! │       │
│                                                └──────────┘       │
└───────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.9+
- tmux (`brew install tmux` on macOS)
- Anthropic API key

### Setup

```bash
# Clone and enter directory
git clone https://github.com/anthropics/service-harness.git
cd service-harness

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .

# Configure environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### Run the Demo

```bash
harness demo
```

This launches a tmux session with three panes:

```
┌───────────────────┬─────────────────┐
│     SERVICE       │    MONITOR      │
│                   │                 │
│  Rate limiter     │  Health checks  │
│  SPACE = dead     │  every 5s       │
│  Z = slow         │                 │
├───────────────────┴─────────────────┤
│              AGENT                  │
│                                     │
│  [1] # Checking service health      │
│      › run_command(curl ...)        │
│  [2] # Reading config file          │
│      › read_file(service_config...) │
│  [3] # Fixing latency issue         │
│      › edit_file(...)               │
│                                     │
└─────────────────────────────────────┘
```

**Chaos Keys (in SERVICE pane):**
- `SPACE` - Toggle "play dead" (service returns 503)
- `Z` - Toggle latency injection (500ms delay, violates <200ms SLO)
- `Q` - Quit

### Watch it Work

1. Select the SERVICE pane (top-left)
2. Press `Z` to inject latency
3. Watch the MONITOR detect the SLO violation
4. Watch the AGENT diagnose and fix the issue automatically

## Architecture

### Components

| Component | Description |
|-----------|-------------|
| **Service** | A rate limiter service on port 8001. The thing being managed. |
| **Monitor** | Checks invariants every 5 seconds. Creates tickets on violations. |
| **Agent** | Claude-powered. Picks up tickets, diagnoses issues, takes action. |
| **Tickets** | SQLite database tracking issues and agent actions. |

### Invariants (SLOs)

The monitor watches two invariants:

```python
# Service must respond with 200
Invariant(
    name="rate_limiter_healthy",
    query="http://localhost:8001/health",
    condition="== 200"
)

# Response time must be under 200ms
Invariant(
    name="rate_limiter_latency",
    query="latency:http://localhost:8001/health",
    condition="< 200"
)
```

### Agent Capabilities

The agent has tools to:
- **Run commands** (`curl`, `ps`, etc.)
- **Read files** (code, config, logs)
- **Edit files** (fix config, patch code)
- **Update tickets** (mark complete, add notes)

The agent is given minimal instructions—just the location of code and config. It figures out the fix by:
1. Checking the health endpoint
2. Reading the error message
3. Investigating config/code
4. Making the fix
5. Verifying it worked

### Haiku Summaries

Each agent step shows a one-liner summary (generated by Claude Haiku):

```
[1] # Checking if service health endpoint responds
    › run_command(command='curl -s http://localhost:8001/health')
[2] # Reading service config to investigate latency
    › read_file(path='service_config.json')
[3] # Removing artificial delay from config
    › edit_file(path='service_config.json', ...)
[4] # Verifying fix resolved the latency issue
    › run_command(command='curl -s http://localhost:8001/health')
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
# Required
ANTHROPIC_API_KEY=your_api_key_here

# Optional (for Grafana Cloud integration)
PROMETHEUS_URL=https://prometheus-xxx.grafana.net/api/prom
PROMETHEUS_USERNAME=your_username
GRAFANA_API_TOKEN=your_token
LOKI_URL=https://logs-xxx.grafana.net
LOKI_USERNAME=your_username
```

## Project Structure

```
service-harness/
├── src/harness/
│   ├── agent/           # Claude-powered ticket worker
│   │   ├── runner.py    # Main agent loop
│   │   └── tools.py     # Agent tool definitions
│   ├── monitor/         # Health check scheduler
│   │   ├── scheduler.py # 5-second check loop
│   │   ├── analyst.py   # Creates intelligent tickets
│   │   └── invariant_evaluator.py
│   ├── service/         # Rate limiter (the managed service)
│   │   └── rate_limiter.py
│   ├── cli.py           # CLI commands (harness demo, etc.)
│   └── supervisor.py    # Process manager
├── tests/               # Test suite
├── docs/plans/          # Design documents
└── .env.example         # Environment template
```

## CLI Commands

```bash
harness demo      # Launch interactive demo in tmux
harness init      # Initialize database and seed invariants
harness run       # Run all processes (without tmux)
harness service   # Run just the rate limiter
harness monitor   # Run just the monitor
harness agent     # Run just the agent
```

## How It Works

### 1. Fault Injection

When you press `Z`, the service writes to `service_config.json`:
```json
{"enabled": true, "delay_ms": 500}
```

The health endpoint reads this and adds artificial delay.

### 2. Detection

The monitor times the health check:
```
Latency: 523.4ms > 200ms threshold
→ SLO violation detected
→ Create ticket for agent
```

### 3. Diagnosis

The agent (Claude) receives the ticket and investigates:
```
Ticket: Fix latency SLO violation
- Health endpoint responding slowly (523ms)
- Let me check the config...
- Found delay_ms: 500 in service_config.json
- That's the problem!
```

### 4. Remediation

The agent edits the config:
```python
edit_file(
    path="service_config.json",
    old_string='"delay_ms": 500',
    new_string='"delay_ms": 0'
)
```

### 5. Verification

The agent confirms the fix:
```
curl health → 12ms response time
✓ Latency back to normal
✓ Ticket completed
```

## Future Directions

This demo shows the basic loop. The full vision includes:

- **Code fixes**: Agent patches actual bugs, not just config
- **Deployment**: Agent can deploy changes through CI/CD
- **Learning**: Agent builds runbooks from successful fixes
- **Multi-service**: Coordinate across dependent services
- **Predictive**: Fix issues before they cause outages

## License

MIT

## Contributing

Contributions welcome! Please read the design docs in `docs/plans/` first.
