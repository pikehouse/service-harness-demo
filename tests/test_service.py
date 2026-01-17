"""Tests for the rate limiter service."""

import pytest
import time
from unittest.mock import Mock, AsyncMock, patch

from fastapi.testclient import TestClient

from harness.service.token_bucket import TokenBucket, TokenBucketConfig
from harness.service.rate_limiter import (
    RateLimiterService,
    RateLimitRequest,
    create_rate_limiter_app,
)


class TestTokenBucket:
    """Tests for TokenBucket."""

    def test_create_bucket(self):
        """Test creating a token bucket."""
        bucket = TokenBucket(capacity=100, refill_rate=10)
        assert bucket.capacity == 100
        assert bucket.refill_rate == 10
        assert bucket.tokens == 100

    def test_create_bucket_with_initial_tokens(self):
        """Test creating bucket with specific initial tokens."""
        bucket = TokenBucket(capacity=100, refill_rate=0, initial_tokens=50)
        assert bucket.tokens == 50

    def test_create_from_config(self):
        """Test creating bucket from config object."""
        config = TokenBucketConfig(capacity=200, refill_rate=20)
        bucket = TokenBucket.from_config(config)
        assert bucket.capacity == 200
        assert bucket.refill_rate == 20

    def test_consume_success(self):
        """Test consuming tokens successfully."""
        bucket = TokenBucket(capacity=100, refill_rate=0)
        assert bucket.consume(1) is True
        assert bucket.tokens == 99

    def test_consume_multiple(self):
        """Test consuming multiple tokens."""
        bucket = TokenBucket(capacity=100, refill_rate=0)
        assert bucket.consume(50) is True
        assert bucket.tokens == 50

    def test_consume_denied(self):
        """Test consuming more tokens than available."""
        bucket = TokenBucket(capacity=10, refill_rate=0, initial_tokens=5)
        assert bucket.consume(10) is False
        assert bucket.tokens == 5  # Unchanged

    def test_consume_exact(self):
        """Test consuming exactly available tokens."""
        bucket = TokenBucket(capacity=100, refill_rate=0, initial_tokens=10)
        assert bucket.consume(10) is True
        assert bucket.tokens == 0

    def test_refill(self):
        """Test that tokens refill over time."""
        bucket = TokenBucket(capacity=100, refill_rate=100, initial_tokens=0)

        # Wait a bit for tokens to refill
        time.sleep(0.1)

        # Should have refilled about 10 tokens (100/sec * 0.1sec)
        tokens = bucket.tokens
        assert 8 <= tokens <= 15  # Allow some timing variance

    def test_refill_capped_at_capacity(self):
        """Test that refill doesn't exceed capacity."""
        bucket = TokenBucket(capacity=100, refill_rate=1000, initial_tokens=90)

        time.sleep(0.1)

        assert bucket.tokens <= 100

    def test_try_consume_success(self):
        """Test try_consume with successful consumption."""
        bucket = TokenBucket(capacity=100, refill_rate=10)
        allowed, remaining, wait_time = bucket.try_consume(10)

        assert allowed is True
        assert remaining == 90
        assert wait_time == 0.0

    def test_try_consume_denied(self):
        """Test try_consume when denied."""
        bucket = TokenBucket(capacity=100, refill_rate=1, initial_tokens=5)
        allowed, remaining, wait_time = bucket.try_consume(10)

        assert allowed is False
        assert 4.9 <= remaining <= 5.1  # Allow small refill variance
        assert wait_time > 0  # Should suggest wait time

    def test_stats(self):
        """Test bucket statistics."""
        bucket = TokenBucket(capacity=100, refill_rate=10)
        bucket.consume(1)  # Allowed
        bucket.consume(1)  # Allowed
        bucket.consume(1000)  # Denied

        stats = bucket.stats
        assert stats["total_requests"] == 3
        assert stats["allowed_requests"] == 2
        assert stats["denied_requests"] == 1

    def test_reset(self):
        """Test resetting bucket."""
        bucket = TokenBucket(capacity=100, refill_rate=10, initial_tokens=10)
        bucket.reset()
        assert bucket.tokens == 100

    def test_reset_to_value(self):
        """Test resetting bucket to specific value."""
        bucket = TokenBucket(capacity=100, refill_rate=0, initial_tokens=10)
        bucket.reset(tokens=50)
        assert bucket.tokens == 50

    def test_thread_safety(self):
        """Test bucket is thread-safe."""
        import threading

        bucket = TokenBucket(capacity=1000, refill_rate=0)  # No refill

        results = []

        def consume_many():
            for _ in range(100):
                results.append(bucket.consume(1))

        threads = [threading.Thread(target=consume_many) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have exactly 1000 allowed (capacity) and 0 denied
        allowed = sum(1 for r in results if r)
        denied = sum(1 for r in results if not r)

        assert allowed == 1000
        assert denied == 0


class TestRateLimiterService:
    """Tests for RateLimiterService."""

    def test_create_service(self):
        """Test creating rate limiter service."""
        service = RateLimiterService(
            default_capacity=100,
            default_refill_rate=10,
        )
        assert service.default_capacity == 100
        assert service.default_refill_rate == 10

    def test_get_or_create_bucket(self):
        """Test automatic bucket creation."""
        service = RateLimiterService()
        bucket = service.get_or_create_bucket("client1")

        assert bucket is not None
        assert "client1" in service._buckets

        # Second call returns same bucket
        bucket2 = service.get_or_create_bucket("client1")
        assert bucket is bucket2

    def test_check_rate_limit_allowed(self):
        """Test checking rate limit when allowed."""
        service = RateLimiterService(default_capacity=100, default_refill_rate=10)
        response = service.check_rate_limit("client1", cost=1.0)

        assert response.allowed is True
        assert response.client_id == "client1"
        assert response.tokens_remaining == 99
        assert response.wait_time_seconds == 0.0

    def test_check_rate_limit_denied(self):
        """Test checking rate limit when denied."""
        service = RateLimiterService(default_capacity=10, default_refill_rate=0)

        # Exhaust bucket
        for _ in range(10):
            service.check_rate_limit("client1")

        response = service.check_rate_limit("client1")
        assert response.allowed is False
        assert response.wait_time_seconds > 0

    def test_service_stats(self):
        """Test service-level statistics."""
        service = RateLimiterService(default_capacity=100, default_refill_rate=10)

        service.check_rate_limit("client1")
        service.check_rate_limit("client2")
        service.check_rate_limit("client1")

        stats = service.get_service_stats()
        assert stats["total_clients"] == 2
        assert stats["total_requests"] == 3
        assert stats["allowed_requests"] == 3

    def test_client_stats(self):
        """Test per-client statistics."""
        service = RateLimiterService()
        service.check_rate_limit("client1")
        service.check_rate_limit("client1")

        stats = service.get_client_stats("client1")
        assert stats is not None
        assert stats["total_requests"] == 2

    def test_client_stats_not_found(self):
        """Test getting stats for unknown client."""
        service = RateLimiterService()
        assert service.get_client_stats("unknown") is None

    def test_configure_client(self):
        """Test configuring client-specific limits."""
        service = RateLimiterService()
        result = service.configure_client("vip_client", capacity=1000, refill_rate=100)

        assert result["capacity"] == 1000
        assert result["refill_rate"] == 100

        bucket = service._buckets["vip_client"]
        assert bucket.capacity == 1000


class TestRateLimiterAPI:
    """Tests for rate limiter HTTP API."""

    @pytest.fixture
    def client(self):
        """Create test client for rate limiter API."""
        service = RateLimiterService(
            default_capacity=100,
            default_refill_rate=10,
        )
        app = create_rate_limiter_app(service=service)
        return TestClient(app)

    def test_health_check(self, client):
        """Test health endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "rate_limiter"

    def test_check_rate_limit(self, client):
        """Test rate limit check endpoint."""
        response = client.post("/v1/check", json={
            "client_id": "test_client",
            "cost": 1.0,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["allowed"] is True
        assert data["client_id"] == "test_client"

    def test_check_rate_limit_minimal(self, client):
        """Test rate limit check with minimal request."""
        response = client.post("/v1/check", json={
            "client_id": "test_client",
        })
        assert response.status_code == 200
        assert response.json()["allowed"] is True

    def test_check_rate_limit_denied(self):
        """Test rate limit when exhausted."""
        # Create service with no refill
        service = RateLimiterService(
            default_capacity=10,
            default_refill_rate=0,
        )
        app = create_rate_limiter_app(service=service)
        client = TestClient(app)

        # Exhaust the bucket
        for _ in range(10):
            client.post("/v1/check", json={"client_id": "heavy_user", "cost": 1.0})

        response = client.post("/v1/check", json={"client_id": "heavy_user"})
        assert response.status_code == 200
        data = response.json()
        assert data["allowed"] is False

    def test_get_stats(self, client):
        """Test getting service stats."""
        # Make some requests first
        client.post("/v1/check", json={"client_id": "client1"})
        client.post("/v1/check", json={"client_id": "client2"})

        response = client.get("/v1/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_requests"] == 2
        assert data["total_clients"] == 2

    def test_get_client(self, client):
        """Test getting client stats."""
        client.post("/v1/check", json={"client_id": "tracked_client"})

        response = client.get("/v1/clients/tracked_client")
        assert response.status_code == 200
        data = response.json()
        assert data["client_id"] == "tracked_client"
        assert data["total_requests"] == 1

    def test_get_client_not_found(self, client):
        """Test getting unknown client."""
        response = client.get("/v1/clients/unknown")
        assert response.status_code == 404

    def test_configure_client(self, client):
        """Test configuring client limits."""
        response = client.put("/v1/clients/vip", json={
            "capacity": 500,
            "refill_rate": 50,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["capacity"] == 500
        assert data["refill_rate"] == 50

    def test_delete_client(self, client):
        """Test deleting client."""
        # Create client first
        client.post("/v1/check", json={"client_id": "temp_client"})

        response = client.delete("/v1/clients/temp_client")
        assert response.status_code == 200

        # Should be gone now
        response = client.get("/v1/clients/temp_client")
        assert response.status_code == 404

    def test_delete_client_not_found(self, client):
        """Test deleting unknown client."""
        response = client.delete("/v1/clients/unknown")
        assert response.status_code == 404


class TestRateLimiterWithObservability:
    """Tests for rate limiter with Prometheus/Loki integration."""

    @pytest.mark.asyncio
    async def test_metrics_push(self):
        """Test that metrics are pushed to Prometheus."""
        mock_prometheus = Mock()

        service = RateLimiterService(
            prometheus_client=mock_prometheus,
            metrics_interval=0.1,
        )

        # Simulate some activity
        service.check_rate_limit("client1")
        service.check_rate_limit("client2")

        # Manually trigger metrics push
        await service._push_metrics()

        # Verify push was called
        mock_prometheus.push_metrics.assert_called_once()
        metrics = mock_prometheus.push_metrics.call_args[0][0]

        # Check metric names
        metric_names = [m["name"] for m in metrics]
        assert "rate_limiter_requests_total" in metric_names
        assert "rate_limiter_requests_allowed" in metric_names
        assert "rate_limiter_active_clients" in metric_names

    def test_log_events(self):
        """Test that events are logged to Loki."""
        mock_loki = Mock()

        service = RateLimiterService(loki_client=mock_loki)
        service.check_rate_limit("client1")

        # Verify log was pushed
        assert mock_loki.push_log.called
        call_args = mock_loki.push_log.call_args
        assert call_args[1]["labels"]["app"] == "rate_limiter"
