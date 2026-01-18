"""Web API for the harness dashboard."""

from harness.web.app import create_app

__all__ = ["create_app", "run_web"]


def run_web(host: str = "0.0.0.0", port: int = 8000):
    """Run the web server."""
    import uvicorn
    app = create_app()
    print(f"Starting web server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
