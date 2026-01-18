"""Token bucket rate limiter implementation."""

import time
import threading
from dataclasses import dataclass
from typing import Optional


@dataclass
class TokenBucketConfig:
    """Configuration for a token bucket."""

    capacity: float  # Maximum tokens in bucket
    refill_rate: float  # Tokens added per second
    initial_tokens: Optional[float] = None  # Starting tokens (defaults to capacity)

    def __post_init__(self):
        if self.initial_tokens is None:
            self.initial_tokens = self.capacity


class TokenBucket:
    """Thread-safe token bucket rate limiter.

    Implements the classic token bucket algorithm:
    - Bucket holds up to 'capacity' tokens
    - Tokens are added at 'refill_rate' per second
    - Each request consumes 'cost' tokens (default 1)
    - If not enough tokens, request is denied

    Example:
        bucket = TokenBucket(capacity=100, refill_rate=10)
        if bucket.consume(1):
            # Request allowed
        else:
            # Request denied (rate limited)
    """

    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        initial_tokens: Optional[float] = None,
    ):
        """Initialize token bucket.

        Args:
            capacity: Maximum tokens the bucket can hold
            refill_rate: Tokens added per second
            initial_tokens: Starting tokens (defaults to capacity)
        """
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._tokens = initial_tokens if initial_tokens is not None else capacity
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

        # Stats
        self._total_requests = 0
        self._allowed_requests = 0
        self._denied_requests = 0

    @classmethod
    def from_config(cls, config: TokenBucketConfig) -> "TokenBucket":
        """Create bucket from configuration."""
        return cls(
            capacity=config.capacity,
            refill_rate=config.refill_rate,
            initial_tokens=config.initial_tokens,
        )

    def _refill(self) -> None:
        """Refill tokens based on time elapsed.

        Must be called with lock held.
        """
        now = time.monotonic()
        elapsed = now - self._last_refill
        tokens_to_add = elapsed * self._refill_rate

        self._tokens = min(self._capacity, self._tokens + tokens_to_add)
        self._last_refill = now

    def consume(self, cost: float = 1.0) -> bool:
        """Try to consume tokens from the bucket.

        Args:
            cost: Number of tokens to consume (default 1)

        Returns:
            True if tokens were consumed, False if denied (not enough tokens)
        """
        with self._lock:
            self._refill()
            self._total_requests += 1

            if self._tokens >= cost:
                self._tokens -= cost
                self._allowed_requests += 1
                return True
            else:
                self._denied_requests += 1
                return False

    def try_consume(self, cost: float = 1.0) -> tuple:
        """Try to consume tokens and return detailed result.

        Args:
            cost: Number of tokens to consume

        Returns:
            Tuple of (allowed: bool, tokens_remaining: float, wait_time: float)
            wait_time is how long to wait until enough tokens if denied
        """
        with self._lock:
            self._refill()
            self._total_requests += 1

            if self._tokens >= cost:
                self._tokens -= cost
                self._allowed_requests += 1
                return (True, self._tokens, 0.0)
            else:
                self._denied_requests += 1
                tokens_needed = cost - self._tokens
                # Cap wait time at 24 hours (86400 seconds) for JSON serialization
                if self._refill_rate > 0:
                    wait_time = min(tokens_needed / self._refill_rate, 86400.0)
                else:
                    wait_time = 86400.0  # No refill means wait forever (capped)
                return (False, self._tokens, wait_time)

    @property
    def tokens(self) -> float:
        """Current number of tokens (triggers refill)."""
        with self._lock:
            self._refill()
            return self._tokens

    @property
    def capacity(self) -> float:
        """Maximum bucket capacity."""
        return self._capacity

    @property
    def refill_rate(self) -> float:
        """Token refill rate per second."""
        return self._refill_rate

    @property
    def stats(self) -> dict:
        """Get current statistics."""
        with self._lock:
            return {
                "total_requests": self._total_requests,
                "allowed_requests": self._allowed_requests,
                "denied_requests": self._denied_requests,
                "tokens": self._tokens,
                "capacity": self._capacity,
                "refill_rate": self._refill_rate,
            }

    def reset(self, tokens: Optional[float] = None) -> None:
        """Reset bucket to specified tokens (defaults to capacity).

        Args:
            tokens: Number of tokens to reset to
        """
        with self._lock:
            self._tokens = tokens if tokens is not None else self._capacity
            self._last_refill = time.monotonic()
