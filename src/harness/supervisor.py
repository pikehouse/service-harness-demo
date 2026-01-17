"""Supervisor process that manages all harness subprocesses."""

import subprocess
import sys
import signal
import time
import os
import re
from typing import Dict, Optional


# ANSI color codes
COLORS = {
    "web": "\033[36m",      # Cyan
    "monitor": "\033[33m",  # Yellow
    "agent": "\033[32m",    # Green
    "service": "\033[35m",  # Magenta
    "reset": "\033[0m",
    "bold": "\033[1m",
}


class Supervisor:
    """Manages harness subprocesses.

    Spawns and monitors:
    - web: FastAPI server on port 8000
    - monitor: Health checks and ticket creation
    - agent: Ticket worker
    - service: Rate limiter on port 8001 (optional)

    Does NOT auto-restart crashed processes - the agent handles recovery.
    """

    # Patterns to filter out in quiet mode
    NOISE_PATTERNS = [
        r"INFO:\s+Started server process",
        r"INFO:\s+Waiting for application startup",
        r"INFO:\s+Application startup complete",
        r"INFO:\s+Uvicorn running on",
        r"INFO:\s+Started reloader process",
        r"INFO:\s+127\.0\.0\.1:\d+ - ",  # HTTP access logs
        r"DEBUG:",
        r"sqlalchemy\.engine\.Engine",
    ]

    def __init__(self, include_service: bool = True, quiet: bool = False):
        self.include_service = include_service
        self.quiet = quiet
        self.processes: Dict[str, subprocess.Popen] = {}
        self.running = False
        self._python = sys.executable
        self._noise_re = re.compile("|".join(self.NOISE_PATTERNS))

    def start(self):
        """Start all subprocesses."""
        self.running = True

        # Set up signal handlers
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        print("Starting harness supervisor...")
        print()

        # Start processes
        self._start_process("web", [self._python, "-m", "harness.cli", "web"])
        self._start_process("monitor", [self._python, "-m", "harness.cli", "monitor"])
        self._start_process("agent", [self._python, "-m", "harness.cli", "agent"])

        if self.include_service:
            self._start_process("service", [self._python, "-m", "harness.cli", "service"])

        print()
        print("All processes started. Press Ctrl+C to stop.")
        print()

        # Monitor loop - just wait and log status
        self._monitor_loop()

    def _print(self, name: str, message: str, force: bool = False):
        """Print a message with colored prefix.

        Args:
            name: Process name (for color selection)
            message: Message to print
            force: Print even in quiet mode
        """
        # Filter noise in quiet mode
        if self.quiet and not force:
            if self._noise_re.search(message):
                return

        color = COLORS.get(name, "")
        reset = COLORS["reset"]
        print(f"  {color}[{name}]{reset} {message}")

    def _start_process(self, name: str, cmd: list):
        """Start a subprocess."""
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"  # Ensure output is not buffered

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
        )
        self.processes[name] = process
        self._print(name, f"Started (PID {process.pid})", force=True)

    def _monitor_loop(self):
        """Main loop - monitor processes and forward output."""
        import select

        # Build fd -> name mapping
        fd_to_name = {}
        for name, proc in self.processes.items():
            if proc.stdout:
                fd_to_name[proc.stdout.fileno()] = (name, proc.stdout)

        while self.running:
            # Check for crashed processes
            for name, proc in list(self.processes.items()):
                ret = proc.poll()
                if ret is not None:
                    self._print(name, f"Process exited with code {ret}", force=True)
                    # Remove from fd mapping
                    if proc.stdout:
                        fd = proc.stdout.fileno()
                        if fd in fd_to_name:
                            del fd_to_name[fd]
                    del self.processes[name]

            if not self.processes:
                print("All processes have exited.")
                break

            # Read output from all processes
            readable_fds = [fd for fd in fd_to_name.keys()]
            if not readable_fds:
                time.sleep(0.1)
                continue

            try:
                readable, _, _ = select.select(readable_fds, [], [], 0.1)
            except (ValueError, OSError):
                # fd closed
                continue

            for fd in readable:
                if fd in fd_to_name:
                    name, stdout = fd_to_name[fd]
                    try:
                        line = stdout.readline()
                        if line:
                            self._print(name, line.rstrip())
                    except (ValueError, OSError):
                        pass

    def _handle_signal(self, signum, frame):
        """Handle shutdown signals."""
        print()
        print("Shutting down...")
        self.running = False
        self.stop()

    def stop(self):
        """Stop all subprocesses."""
        for name, proc in list(self.processes.items()):
            if proc.poll() is None:  # Still running
                print(f"  [{name}] Stopping...")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print(f"  [{name}] Force killing...")
                    proc.kill()
                print(f"  [{name}] Stopped")

        self.processes.clear()
        print("All processes stopped.")


def run_supervisor(include_service: bool = True, quiet: bool = False):
    """Run the supervisor.

    Args:
        include_service: Whether to start the rate limiter service
        quiet: Reduce output noise from uvicorn and SQL logs
    """
    supervisor = Supervisor(include_service=include_service, quiet=quiet)
    supervisor.start()
