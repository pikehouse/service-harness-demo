"""Rate limiter service - the service managed by the harness."""

from harness.service.token_bucket import TokenBucket
from harness.service.rate_limiter import RateLimiterService, create_rate_limiter_app

__all__ = ["TokenBucket", "RateLimiterService", "create_rate_limiter_app", "run_service"]


def run_service(host: str = "0.0.0.0", port: int = 8001):
    """Run the rate limiter service."""
    import uvicorn
    from harness.grafana import PrometheusClient, LokiClient

    print(f"Starting rate limiter service on {host}:{port}")

    # Create observability clients
    try:
        prometheus = PrometheusClient()
        loki = LokiClient()
    except Exception as e:
        print(f"Warning: Could not initialize observability clients: {e}")
        prometheus = None
        loki = None

    app = create_rate_limiter_app(
        prometheus_client=prometheus,
        loki_client=loki,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")
