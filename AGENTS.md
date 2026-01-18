# Harness - AI Agent Guide

## Overview

Harness is an AI-native infrastructure management system. It enables AI agents to monitor, maintain, and improve infrastructure services through a structured workflow.

## Quick Start for Agents

1. **Check current state**: Query the dashboard API or Prometheus for system health
2. **Find open tickets**: `GET /api/tickets?status=open`
3. **Investigate issues**: Use observability tools (Prometheus, Loki) to understand problems
4. **Make changes**: Edit files, run tests, deploy
5. **Document work**: Add notes to tickets, update status

## Architecture

```
harness/
├── src/
│   ├── web/           # Dashboard & REST API
│   ├── agent_loop/    # Agent tools and handlers
│   ├── observability/ # Prometheus/Loki clients
│   ├── invariants/    # Constraint evaluation
│   └── models/        # Database models
├── subjects/          # Managed services
│   └── ratelimiter/   # Token bucket rate limiter
└── scripts/           # Deployment & testing
```

## Core Concepts

### Tickets

Tickets track work items. They can be:
- Created manually or automatically (from invariant violations)
- Updated with notes documenting investigation/progress
- Transitioned through statuses: open → in_progress → resolved → closed

### Invariants

Invariants are system constraints that must hold true. They:
- Are defined with PromQL queries and thresholds
- Get evaluated periodically
- Auto-create tickets when violated

Example invariant:
```
name: ratelimiter_rejection_rate
query: ratelimiter_rejection_rate{bucket="default"}
threshold: 0.05
operator: <
```

### Subjects

Subjects are the infrastructure services being managed. Each subject:
- Lives in `subjects/<name>/`
- Has its own AGENTS.md with domain-specific guidance
- Exports Prometheus metrics
- Has tests that must pass before deployment

## Available Tools

### Observability
- `query_prometheus` - Run PromQL queries
- `query_loki` - Search logs with LogQL

### Knowledge
- `read_file` - Read file contents
- `search_code` - Grep-like code search
- `list_directory` - List directory contents

### Actions
- `edit_file` - Modify existing files
- `create_file` - Create new files
- `run_tests` - Execute tests for a subject
- `deploy` - Deploy a subject service

### Tickets
- `create_ticket` - Create new ticket
- `add_ticket_note` - Add progress notes
- `update_ticket_status` - Change ticket status

## Workflow Guidelines

### Investigating Issues

1. Start with observability data
   - Query relevant Prometheus metrics
   - Search Loki logs for errors
   - Identify patterns and anomalies

2. Examine the codebase
   - Read relevant source files
   - Search for related code
   - Understand the implementation

3. Document findings in ticket notes

### Making Changes

1. Plan the change
   - Identify files to modify
   - Consider impact and risks

2. Implement
   - Make minimal, targeted changes
   - Follow existing code style

3. Verify
   - Run tests: `run_tests(subject="<name>")`
   - Check that tests pass

4. Deploy (only after tests pass)
   - Use `deploy(subject="<name>")`
   - Monitor for issues

### Best Practices

- **Always investigate before changing**: Understand the problem first
- **Document your reasoning**: Add detailed notes to tickets
- **Make minimal changes**: Avoid unnecessary refactoring
- **Test before deploying**: Never deploy without passing tests
- **Monitor after changes**: Check metrics after deployment

## API Reference

### Dashboard API

```
GET  /api/tickets              # List tickets
POST /api/tickets              # Create ticket
GET  /api/tickets/{id}         # Get ticket
PATCH /api/tickets/{id}        # Update ticket
POST /api/tickets/{id}/notes   # Add note

GET  /api/invariants           # List invariants
POST /api/invariants           # Create invariant

GET  /api/actions              # List actions (audit log)
```

### Rate Limiter API

```
POST /acquire/{bucket}         # Try to acquire tokens
GET  /buckets/{bucket}         # Get bucket stats
GET  /metrics                  # Prometheus metrics
```

## Configuration

Environment variables (set in `.env`):
- `ANTHROPIC_API_KEY` - Required for agent
- `GRAFANA_PROMETHEUS_URL/USER/TOKEN` - Prometheus access
- `GRAFANA_LOKI_URL/USER/TOKEN` - Loki access
- `DATABASE_URL` - SQLite database path

## Troubleshooting

### Common Issues

1. **Agent not responding**: Check ANTHROPIC_API_KEY is set
2. **No metrics data**: Verify Grafana credentials
3. **Tests failing**: Read test output, check for missing dependencies
4. **Deploy fails**: Ensure tests pass first, check deploy script output
