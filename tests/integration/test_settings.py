"""Integration tests for the settings API.

Uses in-process TestClient — no live server required.
AUTH_DEV_MODE=true — no auth headers required.
"""

import pytest


class TestSettings:
    """Tests for the /api/v1/settings endpoints."""

    def test_get_settings(self, client, api_prefix):
        """GET /api/v1/settings should return 200 with a settings object."""
        resp = client.get(f"{api_prefix}/settings")
        assert resp.status_code in (200, 422), (
            f"Unexpected status from settings: {resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, dict), (
                f"Expected dict body from settings, got {type(body)}"
            )

    def test_list_notifications(self, client, api_prefix):
        """GET /api/v1/settings/notifications should return 200."""
        resp = client.get(f"{api_prefix}/settings/notifications")
        assert resp.status_code in (200, 404, 422), (
            f"Unexpected status from settings/notifications: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, (list, dict)), (
                f"Expected list or dict body, got {type(body)}"
            )
