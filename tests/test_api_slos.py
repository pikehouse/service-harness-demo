"""Tests for the SLOs API."""

import pytest
from fastapi.testclient import TestClient


class TestSLOsAPI:
    """Tests for the /api/slos endpoints."""

    def test_create_slo(self, client: TestClient):
        """Test creating an SLO."""
        response = client.post(
            "/api/slos",
            json={
                "name": "availability",
                "description": "Service availability SLO",
                "target": 0.999,
                "window_days": 30,
                "metric_query": 'sum(rate(http_requests_total{status!~"5.."}[5m])) / sum(rate(http_requests_total[5m]))',
                "burn_rate_thresholds": {"fast": 14.4, "slow": 1},
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] is not None
        assert data["name"] == "availability"
        assert data["target"] == 0.999
        assert data["window_days"] == 30
        assert data["enabled"] is True
        assert data["burn_rate_thresholds"]["fast"] == 14.4

    def test_create_slo_minimal(self, client: TestClient):
        """Test creating an SLO with minimal data."""
        response = client.post(
            "/api/slos",
            json={
                "name": "latency",
                "target": 0.95,
                "metric_query": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["window_days"] == 30  # Default
        assert data["enabled"] is True  # Default

    def test_create_slo_duplicate_name(self, client: TestClient):
        """Test that duplicate SLO names are rejected."""
        client.post(
            "/api/slos",
            json={"name": "unique_slo", "target": 0.99, "metric_query": "query1"},
        )

        response = client.post(
            "/api/slos",
            json={"name": "unique_slo", "target": 0.95, "metric_query": "query2"},
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    def test_create_slo_invalid_target(self, client: TestClient):
        """Test that invalid targets are rejected."""
        # Target > 1
        response = client.post(
            "/api/slos",
            json={"name": "invalid", "target": 1.5, "metric_query": "query"},
        )
        assert response.status_code == 422

        # Target <= 0
        response = client.post(
            "/api/slos",
            json={"name": "invalid", "target": 0, "metric_query": "query"},
        )
        assert response.status_code == 422

    def test_list_slos_empty(self, client: TestClient):
        """Test listing SLOs when none exist."""
        response = client.get("/api/slos")
        assert response.status_code == 200
        data = response.json()
        assert data["slos"] == []
        assert data["total"] == 0

    def test_list_slos(self, client: TestClient):
        """Test listing SLOs."""
        client.post("/api/slos", json={"name": "slo1", "target": 0.99, "metric_query": "q1"})
        client.post("/api/slos", json={"name": "slo2", "target": 0.95, "metric_query": "q2"})

        response = client.get("/api/slos")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        # Should be ordered by name
        assert data["slos"][0]["name"] == "slo1"
        assert data["slos"][1]["name"] == "slo2"

    def test_list_slos_filter_enabled(self, client: TestClient):
        """Test filtering SLOs by enabled status."""
        r1 = client.post("/api/slos", json={"name": "enabled_slo", "target": 0.99, "metric_query": "q1"})
        r2 = client.post("/api/slos", json={"name": "disabled_slo", "target": 0.95, "metric_query": "q2", "enabled": False})

        # Filter enabled only
        response = client.get("/api/slos?enabled=true")
        data = response.json()
        assert data["total"] == 1
        assert data["slos"][0]["name"] == "enabled_slo"

        # Filter disabled only
        response = client.get("/api/slos?enabled=false")
        data = response.json()
        assert data["total"] == 1
        assert data["slos"][0]["name"] == "disabled_slo"

    def test_get_slo(self, client: TestClient):
        """Test getting an SLO by ID."""
        create_resp = client.post(
            "/api/slos",
            json={"name": "get_me", "target": 0.99, "metric_query": "query"},
        )
        slo_id = create_resp.json()["id"]

        response = client.get(f"/api/slos/{slo_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == slo_id
        assert data["name"] == "get_me"

    def test_get_slo_not_found(self, client: TestClient):
        """Test getting a non-existent SLO."""
        response = client.get("/api/slos/9999")
        assert response.status_code == 404

    def test_update_slo(self, client: TestClient):
        """Test updating an SLO."""
        create_resp = client.post(
            "/api/slos",
            json={"name": "update_me", "target": 0.99, "metric_query": "query"},
        )
        slo_id = create_resp.json()["id"]

        response = client.patch(
            f"/api/slos/{slo_id}",
            json={"target": 0.999, "description": "Updated description"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["target"] == 0.999
        assert data["description"] == "Updated description"

    def test_update_slo_name_duplicate(self, client: TestClient):
        """Test that updating to a duplicate name is rejected."""
        client.post("/api/slos", json={"name": "existing", "target": 0.99, "metric_query": "q1"})
        r2 = client.post("/api/slos", json={"name": "to_rename", "target": 0.95, "metric_query": "q2"})
        slo_id = r2.json()["id"]

        response = client.patch(f"/api/slos/{slo_id}", json={"name": "existing"})
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    def test_delete_slo(self, client: TestClient):
        """Test deleting (disabling) an SLO."""
        create_resp = client.post(
            "/api/slos",
            json={"name": "delete_me", "target": 0.99, "metric_query": "query"},
        )
        slo_id = create_resp.json()["id"]

        # Delete (soft delete)
        response = client.delete(f"/api/slos/{slo_id}")
        assert response.status_code == 204

        # Verify disabled
        get_resp = client.get(f"/api/slos/{slo_id}")
        assert get_resp.json()["enabled"] is False

    def test_delete_slo_not_found(self, client: TestClient):
        """Test deleting a non-existent SLO."""
        response = client.delete("/api/slos/9999")
        assert response.status_code == 404
