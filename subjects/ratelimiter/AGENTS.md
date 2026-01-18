# Rate Limiter Service - Agent Guide

## Overview

This is a token bucket rate limiter service. It provides HTTP endpoints for rate limiting requests across distributed systems.

## Architecture

```
src/
├── bucket.py   # Token bucket algorithm implementation
├── metrics.py  # Prometheus metrics definitions
├── app.py      # FastAPI application and endpoints
└── main.py     # Entry point
```

## Key Components

### TokenBucket (`bucket.py`)

The core rate limiting algorithm:
- Configurable capacity (max tokens)
- Configurable refill rate (tokens/second)
- Thread-safe with locking
- Tracks statistics (total, allowed, rejected)

### API Endpoints (`app.py`)

- `POST /buckets/{name}` - Create/configure a bucket
- `GET /buckets/{name}` - Get bucket stats
- `POST /acquire/{name}` - Try to acquire tokens
- `GET /metrics` - Prometheus metrics

### Metrics (`metrics.py`)

Exports to Prometheus:
- `ratelimiter_requests_total` - Counter by bucket and result
- `ratelimiter_bucket_tokens` - Current available tokens
- `ratelimiter_rejection_rate` - Current rejection rate

## Running

```bash
# Install dependencies
pip install -e .

# Run service
python -m ratelimiter.main

# Or with custom port
RATELIMITER_PORT=8002 python -m ratelimiter.main
```

## Testing

```bash
pytest tests/ -v
```

## Common Issues

1. **High rejection rate**: Bucket capacity or refill rate may be too low for traffic
2. **Memory usage**: Many buckets consume memory; consider cleanup policy
3. **Clock skew**: Token refill depends on monotonic time; should be stable

## Invariants to Monitor

1. Rejection rate should stay below threshold (e.g., 5%)
2. Available tokens should not stay at 0 for extended periods
3. Request latency should remain under 10ms
