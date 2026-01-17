"""Loki client for pushing and querying logs via Grafana Cloud."""

from typing import Optional, Dict, Any, List
from datetime import datetime
import time
import json

import httpx

from harness.config import get_settings


class LokiClient:
    """Client for interacting with Loki via Grafana Cloud.

    Supports:
    - Pushing logs via Loki push API
    - Querying logs via LogQL
    """

    def __init__(
        self,
        url: Optional[str] = None,
        username: Optional[str] = None,
        api_token: Optional[str] = None,
    ):
        """Initialize the Loki client.

        Args:
            url: Loki URL (defaults to settings)
            username: Loki username/instance ID (defaults to settings)
            api_token: Grafana Cloud API token (defaults to settings)
        """
        settings = get_settings()
        self.base_url = (url or settings.loki_url).rstrip("/")
        self.username = username or settings.loki_username
        self.api_token = api_token or settings.grafana_api_token

        self._client = httpx.Client(
            auth=(self.username, self.api_token),
            timeout=30.0,
        )

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def query(
        self,
        logql: str,
        limit: int = 100,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        direction: str = "backward",
    ) -> Dict[str, Any]:
        """Execute a LogQL query.

        Args:
            logql: The LogQL query string
            limit: Maximum number of entries to return
            start: Start time (defaults to 1 hour ago)
            end: End time (defaults to now)
            direction: Query direction ("forward" or "backward")

        Returns:
            Query result as a dictionary
        """
        now = datetime.utcnow()
        if end is None:
            end = now
        if start is None:
            start = datetime.utcnow()
            start = start.replace(hour=start.hour - 1) if start.hour > 0 else start

        # Convert to nanoseconds
        start_ns = int(start.timestamp() * 1_000_000_000)
        end_ns = int(end.timestamp() * 1_000_000_000)

        params = {
            "query": logql,
            "limit": limit,
            "start": str(start_ns),
            "end": str(end_ns),
            "direction": direction,
        }

        response = self._client.get(
            f"{self.base_url}/loki/api/v1/query_range",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    def query_instant(self, logql: str, limit: int = 100) -> Dict[str, Any]:
        """Execute an instant LogQL query.

        Args:
            logql: The LogQL query string
            limit: Maximum number of entries to return

        Returns:
            Query result as a dictionary
        """
        params = {
            "query": logql,
            "limit": limit,
        }

        response = self._client.get(
            f"{self.base_url}/loki/api/v1/query",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    def push_logs(self, streams: List[Dict[str, Any]]) -> None:
        """Push logs to Loki.

        Args:
            streams: List of stream dictionaries with format:
                {
                    "labels": {"label1": "value1", ...},
                    "entries": [
                        {"timestamp": datetime, "line": "log message"},
                        ...
                    ]
                }

                Or simplified format (single entry):
                {
                    "labels": {"label1": "value1", ...},
                    "line": "log message",
                    "timestamp": datetime (optional)
                }
        """
        # Convert to Loki push format
        loki_streams = []

        for stream in streams:
            labels = stream["labels"]

            # Build labels string in Loki format: {label1="value1", label2="value2"}
            label_str = "{" + ", ".join(f'{k}="{v}"' for k, v in sorted(labels.items())) + "}"

            # Get entries
            if "entries" in stream:
                entries = stream["entries"]
            else:
                # Simplified single entry format
                entries = [{
                    "timestamp": stream.get("timestamp") or datetime.utcnow(),
                    "line": stream["line"],
                }]

            # Convert to Loki format
            loki_values = []
            for entry in entries:
                timestamp = entry.get("timestamp") or datetime.utcnow()
                timestamp_ns = str(int(timestamp.timestamp() * 1_000_000_000))
                line = entry["line"]
                loki_values.append([timestamp_ns, line])

            loki_streams.append({
                "stream": labels,
                "values": loki_values,
            })

        # Push to Loki
        response = self._client.post(
            f"{self.base_url}/loki/api/v1/push",
            json={"streams": loki_streams},
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

    def push_log(
        self,
        message: str,
        labels: Dict[str, str],
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Push a single log entry to Loki.

        Convenience method for pushing a single log line.

        Args:
            message: The log message
            labels: Labels for the log stream
            timestamp: Optional timestamp (defaults to now)
        """
        self.push_logs([{
            "labels": labels,
            "line": message,
            "timestamp": timestamp,
        }])

    def get_labels(self) -> List[str]:
        """Get all label names.

        Returns:
            List of label names
        """
        response = self._client.get(f"{self.base_url}/loki/api/v1/labels")
        response.raise_for_status()
        result = response.json()
        return result.get("data", [])

    def get_label_values(self, label: str) -> List[str]:
        """Get all values for a label.

        Args:
            label: The label name

        Returns:
            List of label values
        """
        response = self._client.get(f"{self.base_url}/loki/api/v1/label/{label}/values")
        response.raise_for_status()
        result = response.json()
        return result.get("data", [])

    def check_health(self) -> bool:
        """Check if Loki is reachable.

        Returns:
            True if healthy, False otherwise
        """
        try:
            response = self._client.get(f"{self.base_url}/ready")
            return response.status_code == 200
        except Exception:
            return False

    def tail(
        self,
        logql: str,
        delay_for: int = 0,
        limit: int = 100,
        start: Optional[datetime] = None,
    ):
        """Tail logs (get recent entries).

        Args:
            logql: The LogQL query string
            delay_for: Number of seconds to delay retrieving logs (to allow ingestion)
            limit: Maximum number of entries to return
            start: Start time for the tail

        Returns:
            Query result with recent log entries
        """
        now = datetime.utcnow()
        if start is None:
            # Default to last 5 minutes
            from datetime import timedelta
            start = now - timedelta(minutes=5)

        params = {
            "query": logql,
            "limit": limit,
            "start": str(int(start.timestamp() * 1_000_000_000)),
            "delay_for": delay_for,
        }

        response = self._client.get(
            f"{self.base_url}/loki/api/v1/tail",
            params=params,
        )
        response.raise_for_status()
        return response.json()
