#!/usr/bin/env python3
"""Traffic simulator for testing the rate limiter service."""

import argparse
import asyncio
import random
import time
from dataclasses import dataclass

import httpx


@dataclass
class SimulationStats:
    """Statistics from a simulation run."""
    total_requests: int = 0
    allowed_requests: int = 0
    rejected_requests: int = 0
    errors: int = 0
    total_latency_ms: float = 0.0

    @property
    def rejection_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.rejected_requests / self.total_requests

    @property
    def avg_latency_ms(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_latency_ms / self.total_requests


async def send_request(
    client: httpx.AsyncClient,
    base_url: str,
    bucket: str,
    stats: SimulationStats,
) -> None:
    """Send a single rate limit request."""
    start = time.monotonic()
    try:
        response = await client.post(
            f"{base_url}/acquire/{bucket}",
            json={"tokens": 1},
            timeout=5.0,
        )
        latency_ms = (time.monotonic() - start) * 1000

        stats.total_requests += 1
        stats.total_latency_ms += latency_ms

        if response.status_code == 200:
            data = response.json()
            if data.get("allowed"):
                stats.allowed_requests += 1
            else:
                stats.rejected_requests += 1
        else:
            stats.errors += 1

    except Exception as e:
        stats.errors += 1
        print(f"Request error: {e}")


async def run_simulation(
    base_url: str,
    bucket: str,
    requests_per_second: float,
    duration_seconds: int,
    burst_factor: float = 1.0,
) -> SimulationStats:
    """Run a traffic simulation.

    Args:
        base_url: Rate limiter service URL
        bucket: Bucket name to target
        requests_per_second: Target RPS
        duration_seconds: How long to run
        burst_factor: Random burst multiplier (1.0 = steady, >1.0 = bursty)

    Returns:
        Simulation statistics
    """
    stats = SimulationStats()
    interval = 1.0 / requests_per_second

    print(f"Starting simulation:")
    print(f"  Target: {base_url}/acquire/{bucket}")
    print(f"  RPS: {requests_per_second}")
    print(f"  Duration: {duration_seconds}s")
    print(f"  Burst factor: {burst_factor}")
    print()

    async with httpx.AsyncClient() as client:
        # First, create the bucket with reasonable settings
        await client.post(
            f"{base_url}/buckets/{bucket}",
            json={
                "capacity": int(requests_per_second * 2),
                "refill_rate": requests_per_second,
            },
        )

        start_time = time.monotonic()
        last_report = start_time

        while time.monotonic() - start_time < duration_seconds:
            # Calculate actual interval with optional burstiness
            actual_interval = interval
            if burst_factor > 1.0:
                actual_interval = interval * random.uniform(0.5 / burst_factor, burst_factor)

            # Send request
            await send_request(client, base_url, bucket, stats)

            # Progress report every 5 seconds
            now = time.monotonic()
            if now - last_report >= 5.0:
                elapsed = now - start_time
                current_rps = stats.total_requests / elapsed
                print(
                    f"  Progress: {elapsed:.0f}s | "
                    f"Requests: {stats.total_requests} | "
                    f"RPS: {current_rps:.1f} | "
                    f"Rejection rate: {stats.rejection_rate:.1%}"
                )
                last_report = now

            # Wait for next request
            await asyncio.sleep(actual_interval)

    return stats


async def main():
    parser = argparse.ArgumentParser(description="Simulate traffic to rate limiter")
    parser.add_argument(
        "--url",
        default="http://localhost:8001",
        help="Rate limiter base URL",
    )
    parser.add_argument(
        "--bucket",
        default="test",
        help="Bucket name to target",
    )
    parser.add_argument(
        "--rps",
        type=float,
        default=10.0,
        help="Requests per second",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=30,
        help="Duration in seconds",
    )
    parser.add_argument(
        "--burst",
        type=float,
        default=1.0,
        help="Burst factor (1.0 = steady, 2.0 = bursty)",
    )

    args = parser.parse_args()

    stats = await run_simulation(
        base_url=args.url,
        bucket=args.bucket,
        requests_per_second=args.rps,
        duration_seconds=args.duration,
        burst_factor=args.burst,
    )

    print()
    print("=" * 50)
    print("Simulation Results")
    print("=" * 50)
    print(f"Total requests:    {stats.total_requests}")
    print(f"Allowed:           {stats.allowed_requests}")
    print(f"Rejected:          {stats.rejected_requests}")
    print(f"Errors:            {stats.errors}")
    print(f"Rejection rate:    {stats.rejection_rate:.2%}")
    print(f"Avg latency:       {stats.avg_latency_ms:.2f}ms")


if __name__ == "__main__":
    asyncio.run(main())
