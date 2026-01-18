"""Tests for the token bucket implementation."""

import time
import pytest
from src.bucket import TokenBucket, TokenBucketConfig, RateLimiterRegistry


class TestTokenBucket:
    """Tests for TokenBucket class."""

    def test_initial_tokens(self):
        """Bucket starts with full capacity by default."""
        config = TokenBucketConfig(capacity=100, refill_rate=10.0)
        bucket = TokenBucket(config)
        assert bucket.available_tokens == 100

    def test_initial_tokens_custom(self):
        """Bucket can start with custom initial tokens."""
        config = TokenBucketConfig(capacity=100, refill_rate=0.0, initial_tokens=50)
        bucket = TokenBucket(config)
        assert bucket.available_tokens == 50

    def test_acquire_success(self):
        """Acquiring tokens succeeds when available."""
        bucket = TokenBucket(TokenBucketConfig(capacity=100, refill_rate=0.0))
        assert bucket.acquire(1) is True
        assert bucket.available_tokens == 99

    def test_acquire_multiple(self):
        """Can acquire multiple tokens at once."""
        bucket = TokenBucket(TokenBucketConfig(capacity=100, refill_rate=0.0))
        assert bucket.acquire(50) is True
        assert bucket.available_tokens == 50

    def test_acquire_failure(self):
        """Acquiring fails when not enough tokens."""
        config = TokenBucketConfig(capacity=10, refill_rate=0.0, initial_tokens=5)
        bucket = TokenBucket(config)
        assert bucket.acquire(10) is False
        assert bucket.available_tokens == 5  # Unchanged

    def test_acquire_exact(self):
        """Can acquire exactly all available tokens."""
        config = TokenBucketConfig(capacity=10, refill_rate=0.0, initial_tokens=10)
        bucket = TokenBucket(config)
        assert bucket.acquire(10) is True
        assert bucket.available_tokens == 0

    def test_refill(self):
        """Tokens refill over time."""
        config = TokenBucketConfig(capacity=100, refill_rate=100.0, initial_tokens=0)
        bucket = TokenBucket(config)

        # Wait a bit for refill
        time.sleep(0.1)

        # Should have refilled ~10 tokens (100/sec * 0.1sec)
        tokens = bucket.available_tokens
        assert 5 <= tokens <= 15  # Allow some timing variance

    def test_refill_caps_at_capacity(self):
        """Refill doesn't exceed capacity."""
        config = TokenBucketConfig(capacity=10, refill_rate=100.0, initial_tokens=10)
        bucket = TokenBucket(config)

        time.sleep(0.1)

        assert bucket.available_tokens == 10  # Capped at capacity

    def test_try_acquire_returns_wait_time(self):
        """try_acquire returns wait time when tokens unavailable."""
        config = TokenBucketConfig(capacity=10, refill_rate=10.0, initial_tokens=0)
        bucket = TokenBucket(config)

        success, wait_time = bucket.try_acquire(5)
        assert success is False
        assert 0.4 <= wait_time <= 0.6  # Should need ~0.5 seconds for 5 tokens

    def test_stats(self):
        """Stats are tracked correctly."""
        bucket = TokenBucket(TokenBucketConfig(capacity=100, refill_rate=10.0))

        # Make some requests
        bucket.acquire(1)  # Allowed
        bucket.acquire(1)  # Allowed

        # Drain the bucket
        bucket.acquire(98)  # Allowed

        # This should fail (0 tokens, no refill time)
        bucket._tokens = 0
        bucket.acquire(1)  # Rejected

        stats = bucket.stats
        assert stats["total_requests"] == 4
        assert stats["allowed_requests"] == 3
        assert stats["rejected_requests"] == 1
        assert stats["rejection_rate"] == 0.25

    def test_reset(self):
        """Reset restores bucket to initial state."""
        config = TokenBucketConfig(capacity=100, refill_rate=0.0, initial_tokens=100)
        bucket = TokenBucket(config)

        # Use some tokens
        bucket.acquire(50)
        bucket.acquire(1)  # For stats

        assert bucket.available_tokens == 49

        bucket.reset()

        assert bucket.available_tokens == 100
        stats = bucket.stats
        assert stats["total_requests"] == 0
        assert stats["allowed_requests"] == 0
        assert stats["rejected_requests"] == 0


class TestRateLimiterRegistry:
    """Tests for RateLimiterRegistry class."""

    def test_get_or_create(self):
        """get_or_create creates new buckets."""
        registry = RateLimiterRegistry()
        bucket = registry.get_or_create("test")
        assert bucket is not None
        assert "test" in registry.list_buckets()

    def test_get_or_create_returns_existing(self):
        """get_or_create returns existing bucket."""
        registry = RateLimiterRegistry()
        bucket1 = registry.get_or_create("test")
        bucket2 = registry.get_or_create("test")
        assert bucket1 is bucket2

    def test_get_nonexistent(self):
        """get returns None for nonexistent bucket."""
        registry = RateLimiterRegistry()
        assert registry.get("nonexistent") is None

    def test_delete(self):
        """delete removes bucket."""
        registry = RateLimiterRegistry()
        registry.get_or_create("test")
        assert registry.delete("test") is True
        assert registry.get("test") is None

    def test_delete_nonexistent(self):
        """delete returns False for nonexistent bucket."""
        registry = RateLimiterRegistry()
        assert registry.delete("nonexistent") is False

    def test_list_buckets(self):
        """list_buckets returns all bucket names."""
        registry = RateLimiterRegistry()
        registry.get_or_create("bucket1")
        registry.get_or_create("bucket2")
        registry.get_or_create("bucket3")

        buckets = registry.list_buckets()
        assert set(buckets) == {"bucket1", "bucket2", "bucket3"}

    def test_stats(self):
        """stats returns stats for all buckets."""
        registry = RateLimiterRegistry()
        registry.get_or_create("bucket1")
        registry.get_or_create("bucket2")

        all_stats = registry.stats()
        assert "bucket1" in all_stats
        assert "bucket2" in all_stats
        assert "capacity" in all_stats["bucket1"]
