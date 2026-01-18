"""Token bucket rate limiter implementation."""

import time
import threading
from dataclasses import dataclass
from typing import Optional


@dataclass
class TokenBucketConfig:
    """Configuration for a token bucket."""
    capacity: int = 100  # Maximum tokens in bucket
    refill_rate: float = 10.0  # Tokens per second
    initial_tokens: Optional[int] = None  # Starting tokens (defaults to capacity)


class TokenBucket:
    """Thread-safe token bucket rate limiter.

    The token bucket algorithm works by:
    1. Starting with a bucket full of tokens
    2. Each request consumes one token
    3. Tokens are refilled at a constant rate
    4. If bucket is empty, requests are rejected
    """

    def __init__(self, config: Optional[TokenBucketConfig] = None):
        self.config = config or TokenBucketConfig()
        self._tokens = float(
            self.config.initial_tokens
            if self.config.initial_tokens is not None
            else self.config.capacity
        )
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

        # Statistics
        self._total_requests = 0
        self._allowed_requests = 0
        self._rejected_requests = 0

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        tokens_to_add = elapsed * self.config.refill_rate
        self._tokens = min(self.config.capacity, self._tokens + tokens_to_add)
        self._last_refill = now

    def acquire(self, tokens: int = 1) -> bool:
        """Try to acquire tokens from the bucket.

        Args:
            tokens: Number of tokens to acquire

        Returns:
            True if tokens were acquired, False otherwise
        """
        with self._lock:
            self._refill()
            self._total_requests += 1

            if self._tokens >= tokens:
                self._tokens -= tokens
                self._allowed_requests += 1
                return True
            else:
                self._rejected_requests += 1
                return False

    def try_acquire(self, tokens: int = 1) -> tuple[bool, float]:
        """Try to acquire tokens, returning wait time if not available.

        Args:
            tokens: Number of tokens to acquire

        Returns:
            Tuple of (success, wait_time_seconds)
            If success is True, wait_time is 0
            If success is False, wait_time is how long until tokens available
        """
        with self._lock:
            self._refill()
            self._total_requests += 1

            if self._tokens >= tokens:
                self._tokens -= tokens
                self._allowed_requests += 1
                return True, 0.0
            else:
                self._rejected_requests += 1
                # Calculate how long until enough tokens
                needed = tokens - self._tokens
                wait_time = needed / self.config.refill_rate
                return False, wait_time

    @property
    def available_tokens(self) -> float:
        """Get current available tokens."""
        with self._lock:
            self._refill()
            return self._tokens

    @property
    def stats(self) -> dict:
        """Get bucket statistics."""
        with self._lock:
            return {
                "capacity": self.config.capacity,
                "refill_rate": self.config.refill_rate,
                "available_tokens": self._tokens,
                "total_requests": self._total_requests,
                "allowed_requests": self._allowed_requests,
                "rejected_requests": self._rejected_requests,
                "rejection_rate": (
                    self._rejected_requests / self._total_requests
                    if self._total_requests > 0
                    else 0.0
                ),
            }

    def reset(self) -> None:
        """Reset the bucket to initial state."""
        with self._lock:
            self._tokens = float(
                self.config.initial_tokens
                if self.config.initial_tokens is not None
                else self.config.capacity
            )
            self._last_refill = time.monotonic()
            self._total_requests = 0
            self._allowed_requests = 0
            self._rejected_requests = 0


class RateLimiterRegistry:
    """Registry for multiple named rate limiters."""

    def __init__(self):
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def get_or_create(
        self,
        name: str,
        config: Optional[TokenBucketConfig] = None,
    ) -> TokenBucket:
        """Get existing bucket or create new one."""
        with self._lock:
            if name not in self._buckets:
                self._buckets[name] = TokenBucket(config)
            return self._buckets[name]

    def get(self, name: str) -> Optional[TokenBucket]:
        """Get bucket by name."""
        return self._buckets.get(name)

    def list_buckets(self) -> list[str]:
        """List all bucket names."""
        return list(self._buckets.keys())

    def delete(self, name: str) -> bool:
        """Delete a bucket."""
        with self._lock:
            if name in self._buckets:
                del self._buckets[name]
                return True
            return False

    def stats(self) -> dict[str, dict]:
        """Get stats for all buckets."""
        return {name: bucket.stats for name, bucket in self._buckets.items()}


# Global registry
registry = RateLimiterRegistry()
