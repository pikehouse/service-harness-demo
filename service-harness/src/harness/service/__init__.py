"""Rate limiter service - the service managed by the harness."""

import sys
import threading
import termios
import tty
from typing import Optional

from harness.service.token_bucket import TokenBucket
from harness.service.rate_limiter import RateLimiterService, create_rate_limiter_app

__all__ = ["TokenBucket", "RateLimiterService", "create_rate_limiter_app", "run_service"]


def _keyboard_listener(app, stop_event):
    """Listen for keyboard input to inject chaos."""
    old_settings = None
    try:
        # Save terminal settings and switch to raw mode
        old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())

        while not stop_event.is_set():
            # Check if input is available (non-blocking with select)
            import select
            if select.select([sys.stdin], [], [], 0.1)[0]:
                char = sys.stdin.read(1).lower()

                if char == ' ':
                    # Toggle enabled (play dead)
                    config = app.state.read_config()
                    config["enabled"] = not config.get("enabled", True)
                    app.state.write_config(config)

                    if config["enabled"]:
                        status = "ENABLED ✓"
                        msg = "Service is healthy"
                    else:
                        status = "DISABLED 💀"
                        msg = f"Agent must edit {app.state.config_path} to fix!"

                    print(f"\n{'='*60}", flush=True)
                    print(f"  SERVICE: {status}", flush=True)
                    print(f"  {msg}", flush=True)
                    print(f"{'='*60}\n", flush=True)

                elif char == 'z':
                    # Toggle latency injection
                    config = app.state.read_config()
                    current_delay = config.get("delay_ms", 0)
                    config["delay_ms"] = 0 if current_delay > 0 else 500
                    app.state.write_config(config)

                    if config["delay_ms"] > 0:
                        status = f"SLOW 🐢 ({config['delay_ms']}ms delay)"
                        msg = "Agent must find and fix the latency issue!"
                    else:
                        status = "FAST ⚡"
                        msg = "Latency is normal"

                    print(f"\n{'='*60}", flush=True)
                    print(f"  LATENCY: {status}", flush=True)
                    print(f"  {msg}", flush=True)
                    print(f"{'='*60}\n", flush=True)

                elif char == 'q':
                    break

    except Exception:
        pass  # Terminal not available (e.g., running in background)
    finally:
        if old_settings:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


def run_service(host: str = "0.0.0.0", port: int = 8001):
    """Run the rate limiter service."""
    import uvicorn
    from harness.grafana import PrometheusClient, LokiClient

    print(f"Starting rate limiter service on {host}:{port}")
    print()
    print("  Chaos keys:")
    print("    SPACE = toggle play dead (503 error)")
    print("    Z     = toggle latency injection (500ms delay)")
    print("    Q     = quit")
    print()

    # Create observability clients
    try:
        prometheus = PrometheusClient()
        loki = LokiClient()
    except Exception as e:
        print(f"Warning: Could not initialize observability clients: {e}")
        prometheus = None
        loki = None

    app = create_rate_limiter_app(
        prometheus_client=prometheus,
        loki_client=loki,
    )

    # Start keyboard listener in background thread
    stop_event = threading.Event()
    keyboard_thread = threading.Thread(
        target=_keyboard_listener,
        args=(app, stop_event),
        daemon=True,
    )
    keyboard_thread.start()

    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    finally:
        stop_event.set()
