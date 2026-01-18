"""Prometheus metrics for the rate limiter service."""

from prometheus_client import Counter, Gauge, Histogram, Info

# Service info
SERVICE_INFO = Info(
    "ratelimiter",
    "Rate limiter service information",
)
SERVICE_INFO.info({
    "version": "0.1.0",
    "service": "ratelimiter",
})

# Request metrics
REQUESTS_TOTAL = Counter(
    "ratelimiter_requests_total",
    "Total rate limit check requests",
    ["bucket", "result"],
)

REQUEST_LATENCY = Histogram(
    "ratelimiter_request_latency_seconds",
    "Rate limit check latency",
    ["bucket"],
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1],
)

# Bucket metrics
BUCKET_TOKENS = Gauge(
    "ratelimiter_bucket_tokens",
    "Current available tokens in bucket",
    ["bucket"],
)

BUCKET_CAPACITY = Gauge(
    "ratelimiter_bucket_capacity",
    "Maximum capacity of bucket",
    ["bucket"],
)

BUCKET_REFILL_RATE = Gauge(
    "ratelimiter_bucket_refill_rate",
    "Token refill rate per second",
    ["bucket"],
)

REJECTION_RATE = Gauge(
    "ratelimiter_rejection_rate",
    "Current rejection rate (0-1)",
    ["bucket"],
)


def record_request(bucket_name: str, allowed: bool, latency_seconds: float) -> None:
    """Record a rate limit check request."""
    result = "allowed" if allowed else "rejected"
    REQUESTS_TOTAL.labels(bucket=bucket_name, result=result).inc()
    REQUEST_LATENCY.labels(bucket=bucket_name).observe(latency_seconds)


def update_bucket_metrics(bucket_name: str, stats: dict) -> None:
    """Update bucket gauge metrics."""
    BUCKET_TOKENS.labels(bucket=bucket_name).set(stats.get("available_tokens", 0))
    BUCKET_CAPACITY.labels(bucket=bucket_name).set(stats.get("capacity", 0))
    BUCKET_REFILL_RATE.labels(bucket=bucket_name).set(stats.get("refill_rate", 0))
    REJECTION_RATE.labels(bucket=bucket_name).set(stats.get("rejection_rate", 0))
