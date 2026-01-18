"""Prometheus client for pushing and querying metrics via Grafana Cloud."""

from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import time
import struct
import snappy  # type: ignore

import httpx

from harness.config import get_settings


class PrometheusClient:
    """Client for interacting with Prometheus via Grafana Cloud.

    Supports:
    - Pushing metrics via remote write (Prometheus remote_write protocol)
    - Querying metrics via PromQL
    """

    def __init__(
        self,
        url: Optional[str] = None,
        username: Optional[str] = None,
        api_token: Optional[str] = None,
    ):
        """Initialize the Prometheus client.

        Args:
            url: Prometheus URL (defaults to settings)
            username: Prometheus username/instance ID (defaults to settings)
            api_token: Grafana Cloud API token (defaults to settings)
        """
        settings = get_settings()
        self.base_url = (url or settings.prometheus_url).rstrip("/")
        self.username = username or settings.prometheus_username
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

    def query(self, promql: str, time: Optional[datetime] = None) -> Dict[str, Any]:
        """Execute an instant PromQL query.

        Args:
            promql: The PromQL query string
            time: Optional evaluation time (defaults to now)

        Returns:
            Query result as a dictionary
        """
        params = {"query": promql}
        if time:
            params["time"] = str(time.timestamp())

        response = self._client.get(
            f"{self.base_url}/api/v1/query",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    def query_range(
        self,
        promql: str,
        start: datetime,
        end: datetime,
        step: str = "1m",
    ) -> Dict[str, Any]:
        """Execute a range PromQL query.

        Args:
            promql: The PromQL query string
            start: Start time
            end: End time
            step: Query resolution step (e.g., "1m", "5m", "1h")

        Returns:
            Query result as a dictionary
        """
        params = {
            "query": promql,
            "start": str(start.timestamp()),
            "end": str(end.timestamp()),
            "step": step,
        }

        response = self._client.get(
            f"{self.base_url}/api/v1/query_range",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    def push_metrics(self, metrics: List[Dict[str, Any]]) -> None:
        """Push metrics to Prometheus via remote write.

        This uses the Prometheus remote write protocol with snappy compression.

        Args:
            metrics: List of metric dictionaries with format:
                {
                    "name": "metric_name",
                    "labels": {"label1": "value1", ...},
                    "value": 42.0,
                    "timestamp": datetime (optional, defaults to now)
                }
        """
        # Build the remote write request using protobuf
        write_request = self._build_write_request(metrics)

        # Compress with snappy
        compressed = snappy.compress(write_request)

        # Push to remote write endpoint
        response = self._client.post(
            f"{self.base_url}/push",
            content=compressed,
            headers={
                "Content-Type": "application/x-protobuf",
                "Content-Encoding": "snappy",
                "X-Prometheus-Remote-Write-Version": "0.1.0",
            },
        )
        response.raise_for_status()

    def _build_write_request(self, metrics: List[Dict[str, Any]]) -> bytes:
        """Build a Prometheus remote write request.

        This manually constructs the protobuf message without requiring
        the prometheus-client library.
        """
        # Simple protobuf encoding for WriteRequest
        # WriteRequest { repeated TimeSeries timeseries = 1; }
        # TimeSeries { repeated Label labels = 1; repeated Sample samples = 2; }
        # Label { string name = 1; string value = 2; }
        # Sample { double value = 1; int64 timestamp = 2; }

        timeseries_data = []

        for metric in metrics:
            # Build labels
            labels = [("__name__", metric["name"])]
            if "labels" in metric:
                labels.extend(metric["labels"].items())

            # Build label bytes
            labels_bytes = b""
            for name, value in sorted(labels):
                # Label message: field 1 (name) = string, field 2 (value) = string
                labels_bytes += self._encode_string_field(1, name)
                labels_bytes += self._encode_string_field(2, value)

            # Wrap in Label message container
            label_messages = b""
            for name, value in sorted(labels):
                label_data = self._encode_string_field(1, name) + self._encode_string_field(2, value)
                label_messages += self._encode_message_field(1, label_data)

            # Build sample
            if metric.get("timestamp"):
                timestamp_ms = int(metric["timestamp"].timestamp() * 1000)
            else:
                # Use time.time() for current time (avoids naive datetime timezone issues)
                timestamp_ms = int(time.time() * 1000)
            value = float(metric["value"])

            # Sample message: field 1 (value) = double, field 2 (timestamp) = int64
            sample_data = self._encode_double_field(1, value) + self._encode_int64_field(2, timestamp_ms)
            sample_message = self._encode_message_field(2, sample_data)

            # TimeSeries message
            timeseries_bytes = label_messages + sample_message
            timeseries_data.append(self._encode_message_field(1, timeseries_bytes))

        # WriteRequest message
        return b"".join(timeseries_data)

    def _encode_varint(self, value: int) -> bytes:
        """Encode an integer as a varint."""
        bits = value & 0x7F
        value >>= 7
        result = b""
        while value:
            result += bytes([0x80 | bits])
            bits = value & 0x7F
            value >>= 7
        result += bytes([bits])
        return result

    def _encode_string_field(self, field_num: int, value: str) -> bytes:
        """Encode a string field."""
        data = value.encode("utf-8")
        # Wire type 2 (length-delimited)
        tag = (field_num << 3) | 2
        return self._encode_varint(tag) + self._encode_varint(len(data)) + data

    def _encode_message_field(self, field_num: int, data: bytes) -> bytes:
        """Encode a nested message field."""
        # Wire type 2 (length-delimited)
        tag = (field_num << 3) | 2
        return self._encode_varint(tag) + self._encode_varint(len(data)) + data

    def _encode_double_field(self, field_num: int, value: float) -> bytes:
        """Encode a double field."""
        # Wire type 1 (64-bit)
        tag = (field_num << 3) | 1
        return self._encode_varint(tag) + struct.pack("<d", value)

    def _encode_int64_field(self, field_num: int, value: int) -> bytes:
        """Encode an int64 field."""
        # Wire type 0 (varint)
        tag = (field_num << 3) | 0
        return self._encode_varint(tag) + self._encode_varint(value)

    def get_metric_value(self, promql: str) -> Optional[float]:
        """Get a single metric value from a PromQL query.

        Convenience method for simple queries that return a single value.

        Args:
            promql: The PromQL query string

        Returns:
            The metric value as a float, or None if no data
        """
        result = self.query(promql)
        if result.get("status") != "success":
            return None

        data = result.get("data", {})
        if data.get("resultType") == "vector":
            results = data.get("result", [])
            if results:
                # Return the first result's value
                return float(results[0]["value"][1])

        return None

    def check_health(self) -> bool:
        """Check if Prometheus is reachable.

        Returns:
            True if healthy, False otherwise
        """
        try:
            # Simple query to check connectivity
            result = self.query("up")
            return result.get("status") == "success"
        except Exception:
            return False
