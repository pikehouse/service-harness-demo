"""FastAPI application for the rate limiter service."""

import time
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from .bucket import TokenBucketConfig, registry
from .metrics import record_request, update_bucket_metrics

app = FastAPI(
    title="Rate Limiter Service",
    description="Token bucket rate limiter with Prometheus metrics",
    version="0.1.0",
)


class BucketConfig(BaseModel):
    """Request body for creating/updating a bucket."""
    capacity: int = 100
    refill_rate: float = 10.0
    initial_tokens: Optional[int] = None


class AcquireRequest(BaseModel):
    """Request body for acquiring tokens."""
    tokens: int = 1


class AcquireResponse(BaseModel):
    """Response for acquire requests."""
    allowed: bool
    bucket: str
    tokens_requested: int
    tokens_remaining: float
    wait_time_seconds: Optional[float] = None


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "ratelimiter"}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus metrics endpoint."""
    # Update bucket metrics before generating
    for name in registry.list_buckets():
        bucket = registry.get(name)
        if bucket:
            update_bucket_metrics(name, bucket.stats)

    return PlainTextResponse(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.post("/buckets/{bucket_name}")
async def create_bucket(bucket_name: str, config: BucketConfig):
    """Create or update a rate limit bucket."""
    bucket_config = TokenBucketConfig(
        capacity=config.capacity,
        refill_rate=config.refill_rate,
        initial_tokens=config.initial_tokens,
    )
    bucket = registry.get_or_create(bucket_name, bucket_config)

    return {
        "bucket": bucket_name,
        "created": True,
        "config": {
            "capacity": bucket.config.capacity,
            "refill_rate": bucket.config.refill_rate,
        },
    }


@app.get("/buckets/{bucket_name}")
async def get_bucket(bucket_name: str):
    """Get bucket information and stats."""
    bucket = registry.get(bucket_name)
    if not bucket:
        raise HTTPException(status_code=404, detail="Bucket not found")

    return {
        "bucket": bucket_name,
        "stats": bucket.stats,
    }


@app.delete("/buckets/{bucket_name}")
async def delete_bucket(bucket_name: str):
    """Delete a bucket."""
    if registry.delete(bucket_name):
        return {"bucket": bucket_name, "deleted": True}
    raise HTTPException(status_code=404, detail="Bucket not found")


@app.get("/buckets")
async def list_buckets():
    """List all buckets and their stats."""
    return {
        "buckets": registry.list_buckets(),
        "stats": registry.stats(),
    }


@app.post("/acquire/{bucket_name}", response_model=AcquireResponse)
async def acquire(bucket_name: str, request: AcquireRequest):
    """Try to acquire tokens from a bucket.

    Creates the bucket with default config if it doesn't exist.
    """
    start_time = time.monotonic()

    bucket = registry.get_or_create(bucket_name)
    allowed, wait_time = bucket.try_acquire(request.tokens)

    latency = time.monotonic() - start_time
    record_request(bucket_name, allowed, latency)
    update_bucket_metrics(bucket_name, bucket.stats)

    return AcquireResponse(
        allowed=allowed,
        bucket=bucket_name,
        tokens_requested=request.tokens,
        tokens_remaining=bucket.available_tokens,
        wait_time_seconds=wait_time if not allowed else None,
    )


@app.post("/check/{bucket_name}")
async def check(bucket_name: str, tokens: int = 1):
    """Check if tokens are available without consuming them."""
    bucket = registry.get(bucket_name)
    if not bucket:
        raise HTTPException(status_code=404, detail="Bucket not found")

    available = bucket.available_tokens
    would_allow = available >= tokens

    return {
        "bucket": bucket_name,
        "tokens_requested": tokens,
        "available_tokens": available,
        "would_allow": would_allow,
    }


@app.post("/reset/{bucket_name}")
async def reset_bucket(bucket_name: str):
    """Reset a bucket to its initial state."""
    bucket = registry.get(bucket_name)
    if not bucket:
        raise HTTPException(status_code=404, detail="Bucket not found")

    bucket.reset()
    update_bucket_metrics(bucket_name, bucket.stats)

    return {
        "bucket": bucket_name,
        "reset": True,
        "stats": bucket.stats,
    }
