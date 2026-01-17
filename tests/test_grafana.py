"""Tests for the Grafana Cloud clients (Prometheus and Loki)."""

import pytest
from datetime import datetime, timedelta
import json

import httpx
import respx

from harness.grafana import PrometheusClient, LokiClient


class TestPrometheusClient:
    """Tests for the Prometheus client."""

    @pytest.fixture
    def client(self):
        """Create a Prometheus client with test credentials."""
        return PrometheusClient(
            url="https://prometheus-test.grafana.net/api/prom",
            username="test_user",
            api_token="test_token",
        )

    @respx.mock
    def test_query(self, client):
        """Test executing a PromQL query."""
        mock_response = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {"__name__": "up", "instance": "localhost:9090"},
                        "value": [1609459200, "1"],
                    }
                ],
            },
        }

        respx.get("https://prometheus-test.grafana.net/api/prom/api/v1/query").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        result = client.query("up")

        assert result["status"] == "success"
        assert result["data"]["resultType"] == "vector"
        assert len(result["data"]["result"]) == 1

    @respx.mock
    def test_query_with_time(self, client):
        """Test executing a PromQL query with specific time."""
        mock_response = {"status": "success", "data": {"resultType": "vector", "result": []}}

        route = respx.get("https://prometheus-test.grafana.net/api/prom/api/v1/query").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        specific_time = datetime(2024, 1, 1, 12, 0, 0)
        client.query("up", time=specific_time)

        # Verify time parameter was sent
        assert "time" in route.calls[0].request.url.params

    @respx.mock
    def test_query_range(self, client):
        """Test executing a range PromQL query."""
        mock_response = {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [
                    {
                        "metric": {"__name__": "up"},
                        "values": [[1609459200, "1"], [1609459260, "1"]],
                    }
                ],
            },
        }

        respx.get("https://prometheus-test.grafana.net/api/prom/api/v1/query_range").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        start = datetime(2024, 1, 1, 12, 0, 0)
        end = datetime(2024, 1, 1, 13, 0, 0)
        result = client.query_range("up", start=start, end=end, step="1m")

        assert result["status"] == "success"
        assert result["data"]["resultType"] == "matrix"

    @respx.mock
    def test_get_metric_value(self, client):
        """Test getting a single metric value."""
        mock_response = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {"metric": {"__name__": "cpu_usage"}, "value": [1609459200, "42.5"]}
                ],
            },
        }

        respx.get("https://prometheus-test.grafana.net/api/prom/api/v1/query").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        value = client.get_metric_value("cpu_usage")
        assert value == 42.5

    @respx.mock
    def test_get_metric_value_no_data(self, client):
        """Test getting metric value when no data exists."""
        mock_response = {
            "status": "success",
            "data": {"resultType": "vector", "result": []},
        }

        respx.get("https://prometheus-test.grafana.net/api/prom/api/v1/query").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        value = client.get_metric_value("nonexistent_metric")
        assert value is None

    @respx.mock
    def test_check_health_success(self, client):
        """Test health check when Prometheus is healthy."""
        mock_response = {
            "status": "success",
            "data": {"resultType": "vector", "result": []},
        }

        respx.get("https://prometheus-test.grafana.net/api/prom/api/v1/query").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        assert client.check_health() is True

    @respx.mock
    def test_check_health_failure(self, client):
        """Test health check when Prometheus is unhealthy."""
        respx.get("https://prometheus-test.grafana.net/api/prom/api/v1/query").mock(
            return_value=httpx.Response(500)
        )

        assert client.check_health() is False

    @respx.mock
    def test_push_metrics(self, client):
        """Test pushing metrics to Prometheus."""
        respx.post("https://prometheus-test.grafana.net/api/prom/push").mock(
            return_value=httpx.Response(200)
        )

        metrics = [
            {
                "name": "test_metric",
                "labels": {"env": "test", "host": "localhost"},
                "value": 42.0,
            }
        ]

        # Should not raise
        client.push_metrics(metrics)

    @respx.mock
    def test_push_metrics_with_timestamp(self, client):
        """Test pushing metrics with custom timestamp."""
        respx.post("https://prometheus-test.grafana.net/api/prom/push").mock(
            return_value=httpx.Response(200)
        )

        metrics = [
            {
                "name": "test_metric",
                "value": 100.0,
                "timestamp": datetime(2024, 1, 1, 12, 0, 0),
            }
        ]

        # Should not raise
        client.push_metrics(metrics)

    def test_context_manager(self):
        """Test using client as context manager."""
        with PrometheusClient(
            url="https://test.grafana.net",
            username="user",
            api_token="token",
        ) as client:
            assert client is not None


class TestLokiClient:
    """Tests for the Loki client."""

    @pytest.fixture
    def client(self):
        """Create a Loki client with test credentials."""
        return LokiClient(
            url="https://logs-test.grafana.net",
            username="test_user",
            api_token="test_token",
        )

    @respx.mock
    def test_query(self, client):
        """Test executing a LogQL query."""
        mock_response = {
            "status": "success",
            "data": {
                "resultType": "streams",
                "result": [
                    {
                        "stream": {"app": "test"},
                        "values": [["1609459200000000000", "test log message"]],
                    }
                ],
            },
        }

        respx.get("https://logs-test.grafana.net/loki/api/v1/query_range").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        result = client.query('{app="test"}')

        assert result["status"] == "success"
        assert len(result["data"]["result"]) == 1

    @respx.mock
    def test_query_instant(self, client):
        """Test executing an instant LogQL query."""
        mock_response = {
            "status": "success",
            "data": {"resultType": "streams", "result": []},
        }

        respx.get("https://logs-test.grafana.net/loki/api/v1/query").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        result = client.query_instant('{app="test"}')
        assert result["status"] == "success"

    @respx.mock
    def test_push_logs(self, client):
        """Test pushing logs to Loki."""
        respx.post("https://logs-test.grafana.net/loki/api/v1/push").mock(
            return_value=httpx.Response(204)
        )

        streams = [
            {
                "labels": {"app": "test", "env": "dev"},
                "entries": [
                    {"timestamp": datetime.utcnow(), "line": "Test log message 1"},
                    {"timestamp": datetime.utcnow(), "line": "Test log message 2"},
                ],
            }
        ]

        # Should not raise
        client.push_logs(streams)

    @respx.mock
    def test_push_logs_simplified(self, client):
        """Test pushing logs with simplified format."""
        respx.post("https://logs-test.grafana.net/loki/api/v1/push").mock(
            return_value=httpx.Response(204)
        )

        streams = [
            {
                "labels": {"app": "test"},
                "line": "Single log message",
            }
        ]

        # Should not raise
        client.push_logs(streams)

    @respx.mock
    def test_push_log_single(self, client):
        """Test pushing a single log entry."""
        respx.post("https://logs-test.grafana.net/loki/api/v1/push").mock(
            return_value=httpx.Response(204)
        )

        # Should not raise
        client.push_log(
            message="Test message",
            labels={"app": "test", "level": "info"},
        )

    @respx.mock
    def test_get_labels(self, client):
        """Test getting all label names."""
        mock_response = {
            "status": "success",
            "data": ["app", "env", "level"],
        }

        respx.get("https://logs-test.grafana.net/loki/api/v1/labels").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        labels = client.get_labels()
        assert labels == ["app", "env", "level"]

    @respx.mock
    def test_get_label_values(self, client):
        """Test getting values for a label."""
        mock_response = {
            "status": "success",
            "data": ["production", "staging", "development"],
        }

        respx.get("https://logs-test.grafana.net/loki/api/v1/label/env/values").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        values = client.get_label_values("env")
        assert values == ["production", "staging", "development"]

    @respx.mock
    def test_check_health_success(self, client):
        """Test health check when Loki is healthy."""
        respx.get("https://logs-test.grafana.net/ready").mock(
            return_value=httpx.Response(200, text="ready")
        )

        assert client.check_health() is True

    @respx.mock
    def test_check_health_failure(self, client):
        """Test health check when Loki is unhealthy."""
        respx.get("https://logs-test.grafana.net/ready").mock(
            return_value=httpx.Response(503)
        )

        assert client.check_health() is False

    def test_context_manager(self):
        """Test using client as context manager."""
        with LokiClient(
            url="https://test.grafana.net",
            username="user",
            api_token="token",
        ) as client:
            assert client is not None


class TestPrometheusProtobufEncoding:
    """Tests for the Prometheus protobuf encoding."""

    @pytest.fixture
    def client(self):
        return PrometheusClient(
            url="https://test.grafana.net",
            username="user",
            api_token="token",
        )

    def test_encode_varint_small(self, client):
        """Test varint encoding for small numbers."""
        assert client._encode_varint(0) == b"\x00"
        assert client._encode_varint(1) == b"\x01"
        assert client._encode_varint(127) == b"\x7f"

    def test_encode_varint_large(self, client):
        """Test varint encoding for larger numbers."""
        # 128 = 0x80, should encode as two bytes
        result = client._encode_varint(128)
        assert result == b"\x80\x01"

        # 300 = 0x12c, should encode as two bytes
        result = client._encode_varint(300)
        assert result == b"\xac\x02"

    def test_encode_string_field(self, client):
        """Test string field encoding."""
        result = client._encode_string_field(1, "test")
        # Field 1, wire type 2, length 4, "test"
        assert result == b"\x0a\x04test"

    def test_build_write_request_single_metric(self, client):
        """Test building a write request with a single metric."""
        metrics = [
            {
                "name": "test_metric",
                "labels": {"env": "test"},
                "value": 42.0,
                "timestamp": datetime(2024, 1, 1, 0, 0, 0),
            }
        ]

        result = client._build_write_request(metrics)

        # Should be non-empty bytes
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_build_write_request_multiple_metrics(self, client):
        """Test building a write request with multiple metrics."""
        metrics = [
            {"name": "metric1", "value": 1.0},
            {"name": "metric2", "value": 2.0},
            {"name": "metric3", "labels": {"a": "b"}, "value": 3.0},
        ]

        result = client._build_write_request(metrics)

        # Should be non-empty bytes
        assert isinstance(result, bytes)
        assert len(result) > 0
