"""CLI entry point for the harness."""

import argparse
import sys


def run_demo():
    """Launch demo in tmux with split panes.

    Layout:
    ┌─────────────────┬─────────────────┐
    │     service     │     monitor     │
    ├─────────────────┼─────────────────┤
    │      agent      │      web        │
    └─────────────────┴─────────────────┘
    """
    import subprocess
    import shutil

    # Check if tmux is available
    if not shutil.which("tmux"):
        print("Error: tmux is not installed. Please install tmux first.")
        print("  macOS: brew install tmux")
        print("  Linux: apt install tmux")
        sys.exit(1)

    session_name = "harness-demo"

    # Kill existing session if any
    subprocess.run(["tmux", "kill-session", "-t", session_name],
                   capture_output=True)

    # Enable pane titles
    subprocess.run(["tmux", "set-option", "-g", "pane-border-status", "top"])
    subprocess.run(["tmux", "set-option", "-g", "pane-border-format", " #{pane_title} "])

    # Create new session with first pane (service) - pane 0
    subprocess.run([
        "tmux", "new-session", "-d", "-s", session_name,
        "-n", "harness",
        "harness service"
    ])
    subprocess.run(["tmux", "select-pane", "-T", "SERVICE (rate limiter :8001)"])

    # Split horizontally for monitor (right side) - pane 1
    subprocess.run(["tmux", "split-window", "-h", "-t", session_name, "harness monitor"])
    subprocess.run(["tmux", "select-pane", "-T", "MONITOR (health checks)"])

    # Go back to pane 0 (service) and split vertically for agent - pane 2
    subprocess.run(["tmux", "select-pane", "-t", f"{session_name}:0.0"])
    subprocess.run(["tmux", "split-window", "-v", "-t", session_name, "harness agent"])
    subprocess.run(["tmux", "select-pane", "-T", "AGENT (ticket worker)"])

    # Go to pane 1 (monitor) and split vertically for web - pane 3
    subprocess.run(["tmux", "select-pane", "-t", f"{session_name}:0.1"])
    subprocess.run(["tmux", "split-window", "-v", "-t", session_name, "harness web"])
    subprocess.run(["tmux", "select-pane", "-T", "WEB (API :8000)"])

    # Select the service pane (top left)
    subprocess.run(["tmux", "select-pane", "-t", f"{session_name}:0.0"])

    print(f"Demo started in tmux session '{session_name}'")
    print()
    print("To attach: tmux attach -t harness-demo")
    print("To kill:   tmux kill-session -t harness-demo")
    print()
    print("Demo layout:")
    print("┌─────────────────┬─────────────────┐")
    print("│     service     │     monitor     │")
    print("├─────────────────┼─────────────────┤")
    print("│      agent      │       web       │")
    print("└─────────────────┴─────────────────┘")
    print()
    print("To kill the service and trigger recovery:")
    print("  1. Attach to tmux: tmux attach -t harness-demo")
    print("  2. Select service pane (top-left): Ctrl-b, arrow keys")
    print("  3. Press Ctrl-C to kill it")
    print("  4. Watch monitor detect failure and agent restart it!")

    # Attach to session
    subprocess.run(["tmux", "attach", "-t", session_name])


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

    # harness demo - tmux-based demo with split panes
    subparsers.add_parser("demo", help="Start demo in tmux with split panes")

    # harness run - start all processes
    run_parser = subparsers.add_parser("run", help="Start all harness processes")
    run_parser.add_argument(
        "--no-service",
        action="store_true",
        help="Don't start the rate limiter service (for external service)",
    )
    run_parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Reduce output noise (filter uvicorn/SQL logs)",
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

    elif args.command == "demo":
        run_demo()

    elif args.command == "run":
        from harness.supervisor import run_supervisor
        run_supervisor(include_service=not args.no_service, quiet=args.quiet)

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
