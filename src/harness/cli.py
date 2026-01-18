"""CLI entry point for the harness."""

import argparse
import sys


def run_demo():
    """Launch demo in tmux with split panes.

    Layout:
    ┌───────────────────┬─────────────────┐
    │     SERVICE       │    MONITOR      │
    │  (SPACE=play dead)│                 │
    ├───────────────────┴─────────────────┤
    │           AGENT (full width)        │
    └─────────────────────────────────────┘
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

    print("Cleaning up old state...")

    # Kill existing tmux session if any
    subprocess.run(["tmux", "kill-session", "-t", session_name],
                   capture_output=True)

    # Kill any processes using port 8001 (service)
    result = subprocess.run(["lsof", "-ti", ":8001"], capture_output=True, text=True)
    if result.stdout.strip():
        for pid in result.stdout.strip().split('\n'):
            subprocess.run(["kill", "-9", pid], capture_output=True)
            print(f"  Killed process {pid} on port 8001")

    # Kill any harness processes
    result = subprocess.run(["pgrep", "-f", "harness (service|monitor|agent|web)"],
                           capture_output=True, text=True)
    if result.stdout.strip():
        for pid in result.stdout.strip().split('\n'):
            subprocess.run(["kill", "-9", pid], capture_output=True)
            print(f"  Killed harness process {pid}")

    # Reset the database
    import os
    db_path = os.path.join(os.getcwd(), "harness.db")
    if os.path.exists(db_path):
        os.remove(db_path)
        print("  Removed old database")

    # Re-initialize
    init_harness()
    print()

    # Enable pane titles and keep panes open when process exits
    subprocess.run(["tmux", "set-option", "-g", "pane-border-status", "top"])
    subprocess.run(["tmux", "set-option", "-g", "pane-border-format", " #{pane_title} "])
    subprocess.run(["tmux", "set-option", "-g", "remain-on-exit", "on"])

    # Create new session with first pane (service) - pane 0
    subprocess.run([
        "tmux", "new-session", "-d", "-s", session_name,
        "-n", "harness",
        "harness service"
    ])
    subprocess.run(["tmux", "select-pane", "-T", "SERVICE - Press SPACE to play dead 💀"])

    # Split horizontally for monitor (right side) - pane 1
    subprocess.run(["tmux", "split-window", "-h", "-t", session_name, "harness monitor"])
    subprocess.run(["tmux", "select-pane", "-T", "MONITOR (health checks every 5s)"])

    # Select pane 0 and split vertically for agent (full width bottom)
    subprocess.run(["tmux", "select-pane", "-t", f"{session_name}:0.0"])
    subprocess.run(["tmux", "split-window", "-v", "-t", session_name, "-p", "35", "-f", "harness agent"])
    subprocess.run(["tmux", "select-pane", "-T", "AGENT (ticket worker)"])

    # Select the service pane (top left)
    subprocess.run(["tmux", "select-pane", "-t", f"{session_name}:0.0"])

    print(f"Demo started in tmux session '{session_name}'")
    print()
    print("To attach: tmux attach -t harness-demo")
    print("To kill:   tmux kill-session -t harness-demo")
    print()
    print("Demo layout:")
    print("┌───────────────────┬─────────────────┐")
    print("│     SERVICE       │    MONITOR      │")
    print("│  (SPACE=play dead)│                 │")
    print("├───────────────────┴─────────────────┤")
    print("│           AGENT (full width)        │")
    print("└─────────────────────────────────────┘")
    print()
    print("To trigger the demo:")
    print("  1. Select the SERVICE pane (top-left)")
    print("  2. Press SPACE to make it 'play dead'")
    print("  3. Watch MONITOR detect failure → AGENT fix it!")
    print("  4. Press SPACE again to see it recover")

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
