"""Entry point for the rate limiter service."""

import os
import uvicorn


def main():
    """Run the rate limiter service."""
    host = os.getenv("RATELIMITER_HOST", "0.0.0.0")
    port = int(os.getenv("RATELIMITER_PORT", "8001"))

    print(f"Starting rate limiter service on {host}:{port}")

    uvicorn.run(
        "ratelimiter.app:app",
        host=host,
        port=port,
        reload=False,
        access_log=True,
    )


if __name__ == "__main__":
    main()
