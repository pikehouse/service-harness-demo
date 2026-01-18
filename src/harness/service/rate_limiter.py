"""Rate limiter service with HTTP API and observability."""

import time
import logging
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from harness.config import get_settings
from harness.grafana import PrometheusClient, LokiClient
from harness.service.token_bucket import TokenBucket, TokenBucketConfig

logger = logging.getLogger(__name__)


class RateLimitRequest(BaseModel):
    """Request to check/consume rate limit."""

    client_id: str = Field(..., description="Client identifier")
    cost: float = Field(default=1.0, ge=0.1, le=100.0, description="Token cost")


class RateLimitResponse(BaseModel):
    """Response from rate limit check."""

    allowed: bool
    client_id: str
    tokens_remaining: float
    wait_time_seconds: float = 0.0
    message: str


class BucketConfig(BaseModel):
    """Configuration for a rate limit bucket."""

    capacity: float = Field(100.0, ge=1.0, description="Maximum tokens")
    refill_rate: float = Field(10.0, ge=0.1, description="Tokens per second")


class RateLimiterService:
    """Rate limiter service with multi-client support.

    Features:
    - Per-client token buckets
    - HTTP API for rate limit checks
    - Metrics emission to Prometheus
    - Structured logging to Loki
    - Configurable default limits
    """

    def __init__(
        self,
        default_capacity: float = 100.0,
        default_refill_rate: float = 10.0,
        prometheus_client: Optional[PrometheusClient] = None,
        loki_client: Optional[LokiClient] = None,
        metrics_interval: float = 15.0,
    ):
        """Initialize rate limiter service.

        Args:
            default_capacity: Default bucket capacity for new clients
            default_refill_rate: Default refill rate for new clients
            prometheus_client: Optional Prometheus client for metrics
            loki_client: Optional Loki client for logs
            metrics_interval: Seconds between metrics pushes
        """
        self.default_capacity = default_capacity
        self.default_refill_rate = default_refill_rate
        self._buckets: Dict[str, TokenBucket] = {}
        self._prometheus = prometheus_client
        self._loki = loki_client
        self._metrics_interval = metrics_interval
        self._metrics_task: Optional[asyncio.Task] = None
        self._running = False

        # Service-level stats
        self._start_time = time.time()
        self._total_requests = 0
        self._allowed_requests = 0
        self._denied_requests = 0

    def get_or_create_bucket(self, client_id: str) -> TokenBucket:
        """Get bucket for client, creating if needed."""
        if client_id not in self._buckets:
            self._buckets[client_id] = TokenBucket(
                capacity=self.default_capacity,
                refill_rate=self.default_refill_rate,
            )
            self._log_event("bucket_created", {"client_id": client_id})
        return self._buckets[client_id]

    def check_rate_limit(self, client_id: str, cost: float = 1.0) -> RateLimitResponse:
        """Check rate limit for a client.

        Args:
            client_id: Client identifier
            cost: Number of tokens to consume

        Returns:
            RateLimitResponse with result
        """
        start_time = time.time()
        bucket = self.get_or_create_bucket(client_id)
        allowed, tokens_remaining, wait_time = bucket.try_consume(cost)

        # Update service stats
        self._total_requests += 1
        if allowed:
            self._allowed_requests += 1
        else:
            self._denied_requests += 1

        latency = time.time() - start_time

        # Log the request
        self._log_event(
            "rate_limit_check",
            {
                "client_id": client_id,
                "cost": cost,
                "allowed": allowed,
                "tokens_remaining": tokens_remaining,
                "latency_ms": latency * 1000,
            },
            level="info" if allowed else "warning",
        )

        if allowed:
            message = f"Request allowed. {tokens_remaining:.1f} tokens remaining."
        else:
            message = f"Rate limited. Retry after {wait_time:.2f}s"

        return RateLimitResponse(
            allowed=allowed,
            client_id=client_id,
            tokens_remaining=tokens_remaining,
            wait_time_seconds=wait_time,
            message=message,
        )

    def get_client_stats(self, client_id: str) -> Optional[dict]:
        """Get stats for a specific client."""
        if client_id not in self._buckets:
            return None
        return self._buckets[client_id].stats

    def get_service_stats(self) -> dict:
        """Get overall service statistics."""
        uptime = time.time() - self._start_time
        return {
            "uptime_seconds": uptime,
            "total_clients": len(self._buckets),
            "total_requests": self._total_requests,
            "allowed_requests": self._allowed_requests,
            "denied_requests": self._denied_requests,
            "denial_rate": self._denied_requests / max(1, self._total_requests),
            "default_capacity": self.default_capacity,
            "default_refill_rate": self.default_refill_rate,
        }

    def configure_client(
        self,
        client_id: str,
        capacity: Optional[float] = None,
        refill_rate: Optional[float] = None,
    ) -> dict:
        """Configure rate limit for a specific client.

        Args:
            client_id: Client identifier
            capacity: New capacity (None to keep current)
            refill_rate: New refill rate (None to keep current)

        Returns:
            New configuration
        """
        cap = capacity if capacity is not None else self.default_capacity
        rate = refill_rate if refill_rate is not None else self.default_refill_rate

        self._buckets[client_id] = TokenBucket(
            capacity=cap,
            refill_rate=rate,
        )

        self._log_event(
            "client_configured",
            {
                "client_id": client_id,
                "capacity": cap,
                "refill_rate": rate,
            },
        )

        return {"client_id": client_id, "capacity": cap, "refill_rate": rate}

    def _log_event(
        self,
        event_type: str,
        data: Dict[str, Any],
        level: str = "info",
    ) -> None:
        """Log event to both local logger and Loki."""
        log_data = {
            "event": event_type,
            "service": "rate_limiter",
            **data,
        }

        # Local logging
        log_msg = f"[{event_type}] {data}"
        if level == "warning":
            logger.warning(log_msg)
        elif level == "error":
            logger.error(log_msg)
        else:
            logger.info(log_msg)

        # Push to Loki if available
        if self._loki:
            try:
                import json
                self._loki.push_log(
                    labels={"app": "rate_limiter", "event": event_type},
                    message=json.dumps(log_data),
                )
            except Exception as e:
                logger.debug(f"Failed to push log to Loki: {e}")

    async def _push_metrics(self) -> None:
        """Push metrics to Prometheus."""
        if not self._prometheus:
            return

        try:
            stats = self.get_service_stats()
            metrics = []

            # Service-level metrics
            metrics.append({
                "name": "rate_limiter_requests_total",
                "value": stats["total_requests"],
                "labels": {"service": "rate_limiter"},
            })
            metrics.append({
                "name": "rate_limiter_requests_allowed",
                "value": stats["allowed_requests"],
                "labels": {"service": "rate_limiter"},
            })
            metrics.append({
                "name": "rate_limiter_requests_denied",
                "value": stats["denied_requests"],
                "labels": {"service": "rate_limiter"},
            })
            metrics.append({
                "name": "rate_limiter_active_clients",
                "value": stats["total_clients"],
                "labels": {"service": "rate_limiter"},
            })
            metrics.append({
                "name": "rate_limiter_uptime_seconds",
                "value": stats["uptime_seconds"],
                "labels": {"service": "rate_limiter"},
            })

            # Per-client bucket tokens
            for client_id, bucket in self._buckets.items():
                metrics.append({
                    "name": "rate_limiter_bucket_tokens",
                    "value": bucket.tokens,
                    "labels": {"service": "rate_limiter", "client_id": client_id},
                })

            self._prometheus.push_metrics(metrics)
            logger.debug(f"Pushed {len(metrics)} metrics to Prometheus")

        except Exception as e:
            logger.error(f"Failed to push metrics: {e}")

    async def _metrics_loop(self) -> None:
        """Background task to push metrics periodically."""
        while self._running:
            await self._push_metrics()
            await asyncio.sleep(self._metrics_interval)

    async def start(self) -> None:
        """Start the service (metrics pushing)."""
        self._running = True
        self._start_time = time.time()

        if self._prometheus:
            self._metrics_task = asyncio.create_task(self._metrics_loop())

        self._log_event("service_started", {
            "default_capacity": self.default_capacity,
            "default_refill_rate": self.default_refill_rate,
        })

    async def stop(self) -> None:
        """Stop the service."""
        self._running = False

        if self._metrics_task:
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass

        self._log_event("service_stopped", self.get_service_stats())


def create_rate_limiter_app(
    service: Optional[RateLimiterService] = None,
    **kwargs,
) -> FastAPI:
    """Create FastAPI app for rate limiter service.

    Args:
        service: Optional pre-configured service
        **kwargs: Passed to RateLimiterService if service not provided

    Returns:
        FastAPI application
    """
    rate_limiter = service or RateLimiterService(**kwargs)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await rate_limiter.start()
        yield
        await rate_limiter.stop()

    app = FastAPI(
        title="Rate Limiter Service",
        description="Token bucket rate limiter with observability",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Play dead state - can be toggled to simulate service failure
    app.state.playing_dead = False

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        if app.state.playing_dead:
            raise HTTPException(status_code=503, detail="Service unavailable (playing dead)")
        return {"status": "healthy", "service": "rate_limiter"}

    @app.post("/v1/check", response_model=RateLimitResponse)
    async def check_rate_limit(request: RateLimitRequest):
        """Check rate limit for a client.

        Consumes tokens if allowed, returns denial info if not.
        """
        return rate_limiter.check_rate_limit(request.client_id, request.cost)

    @app.get("/v1/stats")
    async def get_stats():
        """Get service-wide statistics."""
        return rate_limiter.get_service_stats()

    @app.get("/v1/clients/{client_id}")
    async def get_client(client_id: str):
        """Get stats for a specific client."""
        stats = rate_limiter.get_client_stats(client_id)
        if stats is None:
            raise HTTPException(status_code=404, detail="Client not found")
        return {"client_id": client_id, **stats}

    @app.put("/v1/clients/{client_id}")
    async def configure_client(client_id: str, config: BucketConfig):
        """Configure rate limit for a specific client."""
        return rate_limiter.configure_client(
            client_id,
            capacity=config.capacity,
            refill_rate=config.refill_rate,
        )

    @app.delete("/v1/clients/{client_id}")
    async def delete_client(client_id: str):
        """Remove a client's rate limit configuration."""
        if client_id not in rate_limiter._buckets:
            raise HTTPException(status_code=404, detail="Client not found")
        del rate_limiter._buckets[client_id]
        return {"deleted": client_id}

    # Store service reference on app for testing
    app.state.rate_limiter = rate_limiter

    return app
