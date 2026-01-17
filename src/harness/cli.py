"""CLI entry point for the harness."""

import argparse
import sys


def init_harness():
    """Initialize the database and seed data."""
    from harness.database import init_db, get_session
    from harness.models import Invariant

    print("Initializing harness...")

    # Initialize database
    print("  Creating database tables...")
    init_db()

    # Seed the health check invariant
    print("  Seeding health check invariant...")
    with get_session() as db:
        # Check if it already exists
        existing = db.query(Invariant).filter(Invariant.name == "rate_limiter_healthy").first()
        if existing:
            print("    Health check invariant already exists, skipping")
        else:
            invariant = Invariant(
                name="rate_limiter_healthy",
                description="Rate limiter service responds to health checks",
                query="http://localhost:8001/health",
                condition="== 200",
                enabled=True,
            )
            db.add(invariant)
            db.commit()
            print(f"    Created invariant: {invariant.name}")

    print("Done!")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="harness",
        description="AI-native infrastructure harness",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # harness init - initialize database and seed data
    subparsers.add_parser("init", help="Initialize database and seed data")

    # harness run - start all processes
    run_parser = subparsers.add_parser("run", help="Start all harness processes")
    run_parser.add_argument(
        "--no-service",
        action="store_true",
        help="Don't start the rate limiter service (for external service)",
    )

    # harness web - just the web server
    web_parser = subparsers.add_parser("web", help="Start only the web server")
    web_parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    web_parser.add_argument("--port", type=int, default=8000, help="Port to bind to")

    # harness monitor - just the monitor
    subparsers.add_parser("monitor", help="Start only the monitor process")

    # harness agent - just the agent
    subparsers.add_parser("agent", help="Start only the agent process")

    # harness service - just the rate limiter
    service_parser = subparsers.add_parser("service", help="Start only the rate limiter service")
    service_parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    service_parser.add_argument("--port", type=int, default=8001, help="Port to bind to")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "init":
        init_harness()

    elif args.command == "run":
        from harness.supervisor import run_supervisor
        run_supervisor(include_service=not args.no_service)

    elif args.command == "web":
        from harness.web import run_web
        run_web(host=args.host, port=args.port)

    elif args.command == "monitor":
        from harness.monitor import run_monitor
        run_monitor()

    elif args.command == "agent":
        from harness.agent import run_agent
        run_agent()

    elif args.command == "service":
        from harness.service import run_service
        run_service(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
