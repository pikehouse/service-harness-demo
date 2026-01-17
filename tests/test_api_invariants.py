"""Tests for the Invariants API."""

import pytest
from fastapi.testclient import TestClient


class TestInvariantsAPI:
    """Tests for the /api/invariants endpoints."""

    def test_create_invariant(self, client: TestClient):
        """Test creating an invariant."""
        response = client.post(
            "/api/invariants",
            json={
                "name": "capacity_headroom",
                "description": "Ensure capacity headroom > 20%",
                "query": "(1 - (sum(container_memory_usage_bytes) / sum(container_spec_memory_limit_bytes))) * 100",
                "condition": "> 20",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] is not None
        assert data["name"] == "capacity_headroom"
        assert data["condition"] == "> 20"
        assert data["enabled"] is True

    def test_create_invariant_minimal(self, client: TestClient):
        """Test creating an invariant with minimal data."""
        response = client.post(
            "/api/invariants",
            json={
                "name": "no_errors",
                "query": "count(rate(error_total[1m]))",
                "condition": "== 0",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["enabled"] is True  # Default

    def test_create_invariant_duplicate_name(self, client: TestClient):
        """Test that duplicate invariant names are rejected."""
        client.post(
            "/api/invariants",
            json={"name": "unique_inv", "query": "query1", "condition": "> 0"},
        )

        response = client.post(
            "/api/invariants",
            json={"name": "unique_inv", "query": "query2", "condition": "< 100"},
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    def test_list_invariants_empty(self, client: TestClient):
        """Test listing invariants when none exist."""
        response = client.get("/api/invariants")
        assert response.status_code == 200
        data = response.json()
        assert data["invariants"] == []
        assert data["total"] == 0

    def test_list_invariants(self, client: TestClient):
        """Test listing invariants."""
        client.post("/api/invariants", json={"name": "inv1", "query": "q1", "condition": "> 0"})
        client.post("/api/invariants", json={"name": "inv2", "query": "q2", "condition": "< 100"})

        response = client.get("/api/invariants")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        # Should be ordered by name
        assert data["invariants"][0]["name"] == "inv1"
        assert data["invariants"][1]["name"] == "inv2"

    def test_list_invariants_filter_enabled(self, client: TestClient):
        """Test filtering invariants by enabled status."""
        client.post("/api/invariants", json={"name": "enabled_inv", "query": "q1", "condition": "> 0"})
        client.post("/api/invariants", json={"name": "disabled_inv", "query": "q2", "condition": "> 0", "enabled": False})

        # Filter enabled only
        response = client.get("/api/invariants?enabled=true")
        data = response.json()
        assert data["total"] == 1
        assert data["invariants"][0]["name"] == "enabled_inv"

        # Filter disabled only
        response = client.get("/api/invariants?enabled=false")
        data = response.json()
        assert data["total"] == 1
        assert data["invariants"][0]["name"] == "disabled_inv"

    def test_get_invariant(self, client: TestClient):
        """Test getting an invariant by ID."""
        create_resp = client.post(
            "/api/invariants",
            json={"name": "get_me", "query": "query", "condition": "> 0"},
        )
        inv_id = create_resp.json()["id"]

        response = client.get(f"/api/invariants/{inv_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == inv_id
        assert data["name"] == "get_me"

    def test_get_invariant_not_found(self, client: TestClient):
        """Test getting a non-existent invariant."""
        response = client.get("/api/invariants/9999")
        assert response.status_code == 404

    def test_update_invariant(self, client: TestClient):
        """Test updating an invariant."""
        create_resp = client.post(
            "/api/invariants",
            json={"name": "update_me", "query": "query", "condition": "> 0"},
        )
        inv_id = create_resp.json()["id"]

        response = client.patch(
            f"/api/invariants/{inv_id}",
            json={"condition": "> 10", "description": "Updated description"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["condition"] == "> 10"
        assert data["description"] == "Updated description"

    def test_update_invariant_name_duplicate(self, client: TestClient):
        """Test that updating to a duplicate name is rejected."""
        client.post("/api/invariants", json={"name": "existing", "query": "q1", "condition": "> 0"})
        r2 = client.post("/api/invariants", json={"name": "to_rename", "query": "q2", "condition": "> 0"})
        inv_id = r2.json()["id"]

        response = client.patch(f"/api/invariants/{inv_id}", json={"name": "existing"})
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    def test_delete_invariant(self, client: TestClient):
        """Test deleting (disabling) an invariant."""
        create_resp = client.post(
            "/api/invariants",
            json={"name": "delete_me", "query": "query", "condition": "> 0"},
        )
        inv_id = create_resp.json()["id"]

        # Delete (soft delete)
        response = client.delete(f"/api/invariants/{inv_id}")
        assert response.status_code == 204

        # Verify disabled
        get_resp = client.get(f"/api/invariants/{inv_id}")
        assert get_resp.json()["enabled"] is False

    def test_delete_invariant_not_found(self, client: TestClient):
        """Test deleting a non-existent invariant."""
        response = client.delete("/api/invariants/9999")
        assert response.status_code == 404

    def test_update_invariant_enable_disable(self, client: TestClient):
        """Test enabling/disabling an invariant via update."""
        create_resp = client.post(
            "/api/invariants",
            json={"name": "toggle_me", "query": "query", "condition": "> 0"},
        )
        inv_id = create_resp.json()["id"]

        # Disable
        response = client.patch(f"/api/invariants/{inv_id}", json={"enabled": False})
        assert response.status_code == 200
        assert response.json()["enabled"] is False

        # Re-enable
        response = client.patch(f"/api/invariants/{inv_id}", json={"enabled": True})
        assert response.status_code == 200
        assert response.json()["enabled"] is True
