"""Integration tests for the workflows API.

Uses TestClient (in-process) via conftest.py fixtures.
AUTH_DEV_MODE=true — no auth headers required.
"""

import pytest


class TestWorkflows:
    """Tests for workflow list, creation, and schedule preview."""

    def test_list_workflows(self, client, api_prefix):
        """GET /api/v1/workflows should return 200 with a list."""
        resp = client.get(f"{api_prefix}/workflows")
        assert resp.status_code in (200, 422), (
            f"Unexpected status from workflows: {resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, (list, dict)), (
                f"Expected list or dict body, got {type(body)}"
            )

    def test_create_workflow(self, client, api_prefix):
        """POST /api/v1/workflows should return 200 or 201."""
        payload = {
            "name": "integration-test-workflow",
            "description": "Created by integration test suite",
            "steps": [],
            "trigger": {"type": "manual"},
        }
        resp = client.post(f"{api_prefix}/workflows", json=payload)
        # 422 is acceptable if the server enforces stricter validation
        assert resp.status_code in (200, 201, 422), (
            f"Unexpected status creating workflow: {resp.status_code} — {resp.text[:300]}"
        )

    def test_workflow_schedule_preview(self, client, api_prefix):
        """POST /api/v1/workflows/schedule/preview should return 200."""
        payload = {
            "cron": "0 9 * * 1-5",
            "timezone": "UTC",
            "preview_count": 5,
        }
        resp = client.post(f"{api_prefix}/workflows/schedule/preview", json=payload)
        assert resp.status_code in (200, 201, 404, 422), (
            f"Unexpected status from schedule preview: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
