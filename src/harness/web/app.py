"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from harness import __version__
from harness.web.routes import tickets, slos, invariants


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Service Harness",
        description="AI-native infrastructure harness for autonomous service operation",
        version=__version__,
    )

    # Add CORS middleware for development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    app.include_router(tickets.router, prefix="/api/tickets", tags=["tickets"])
    app.include_router(slos.router, prefix="/api/slos", tags=["slos"])
    app.include_router(invariants.router, prefix="/api/invariants", tags=["invariants"])

    @app.get("/health")
    def health_check():
        """Basic health check endpoint."""
        return {"status": "ok", "version": __version__}

    return app


# Create the default app instance
app = create_app()
