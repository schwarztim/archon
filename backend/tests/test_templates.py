"""Tests for Template CRUD routes and instantiation using mocked service layer."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

from fastapi.testclient import TestClient

from app.models import Agent, Template
from tests.conftest import AGENT_ID, NOW, OWNER_ID

# ── Fixed UUIDs ─────────────────────────────────────────────────────

TEMPLATE_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
AUTHOR_ID = OWNER_ID


# ── Fixtures ────────────────────────────────────────────────────────

def _sample_template(**overrides: Any) -> Template:
    """Build a Template model instance with sensible defaults."""
    defaults: dict[str, Any] = {
        "id": TEMPLATE_ID,
        "name": "Customer Support Bot",
        "description": "A chatbot template for customer support",
        "category": "customer_support",
        "definition": {"model": "gpt-4", "nodes": [], "edges": []},
        "tags": ["chatbot", "support"],
        "is_featured": True,
        "usage_count": 5,
        "author_id": AUTHOR_ID,
        "created_at": NOW,
        "updated_at": NOW,
    }
    defaults.update(overrides)
    return Template(**defaults)


def _sample_template_data(**overrides: Any) -> dict[str, Any]:
    """Build raw dict matching TemplateCreate schema."""
    defaults: dict[str, Any] = {
        "name": "Customer Support Bot",
        "description": "A chatbot template for customer support",
        "category": "customer_support",
        "definition": {"model": "gpt-4", "nodes": [], "edges": []},
        "tags": ["chatbot", "support"],
        "is_featured": True,
        "author_id": str(AUTHOR_ID),
    }
    defaults.update(overrides)
    return defaults


# ── List templates ──────────────────────────────────────────────────


def test_list_templates_envelope(client: TestClient) -> None:
    """GET /api/v1/templates/ returns envelope with data + meta + pagination."""
    template = _sample_template()
    with patch(
        "app.routes.templates.TemplateService.list",
        new_callable=AsyncMock,
        return_value=([template], 1),
    ):
        resp = client.get("/api/v1/templates/")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "meta" in body
    assert "pagination" in body["meta"]
    assert body["meta"]["pagination"]["total"] == 1
    assert len(body["data"]) == 1


def test_list_templates_with_category_filter(client: TestClient) -> None:
    """GET /api/v1/templates/?category=... passes filter to service."""
    with patch(
        "app.routes.templates.TemplateService.list",
        new_callable=AsyncMock,
        return_value=([], 0),
    ) as mock_list:
        resp = client.get("/api/v1/templates/?category=data_analysis")
    assert resp.status_code == 200
    mock_list.assert_awaited_once()
    call_kwargs = mock_list.call_args[1]
    assert call_kwargs["category"] == "data_analysis"


def test_list_templates_with_search(client: TestClient) -> None:
    """GET /api/v1/templates/?search=... passes search to service."""
    with patch(
        "app.routes.templates.TemplateService.list",
        new_callable=AsyncMock,
        return_value=([], 0),
    ) as mock_list:
        resp = client.get("/api/v1/templates/?search=chatbot")
    assert resp.status_code == 200
    call_kwargs = mock_list.call_args[1]
    assert call_kwargs["search"] == "chatbot"


def test_list_templates_with_tag_filter(client: TestClient) -> None:
    """GET /api/v1/templates/?tag=... passes tag to service."""
    with patch(
        "app.routes.templates.TemplateService.list",
        new_callable=AsyncMock,
        return_value=([], 0),
    ) as mock_list:
        resp = client.get("/api/v1/templates/?tag=support")
    assert resp.status_code == 200
    call_kwargs = mock_list.call_args[1]
    assert call_kwargs["tag"] == "support"


def test_list_templates_with_featured_filter(client: TestClient) -> None:
    """GET /api/v1/templates/?is_featured=true passes featured filter."""
    with patch(
        "app.routes.templates.TemplateService.list",
        new_callable=AsyncMock,
        return_value=([], 0),
    ) as mock_list:
        resp = client.get("/api/v1/templates/?is_featured=true")
    assert resp.status_code == 200
    call_kwargs = mock_list.call_args[1]
    assert call_kwargs["is_featured"] is True


def test_list_templates_pagination(client: TestClient) -> None:
    """GET /api/v1/templates/?limit=5&offset=10 passes pagination params."""
    with patch(
        "app.routes.templates.TemplateService.list",
        new_callable=AsyncMock,
        return_value=([], 0),
    ) as mock_list:
        resp = client.get("/api/v1/templates/?limit=5&offset=10")
    assert resp.status_code == 200
    call_kwargs = mock_list.call_args[1]
    assert call_kwargs["limit"] == 5
    assert call_kwargs["offset"] == 10


# ── Create template ─────────────────────────────────────────────────


def test_create_template(client: TestClient) -> None:
    """POST /api/v1/templates/ returns 201 with created template in envelope."""
    template = _sample_template()
    data = _sample_template_data()
    with patch(
        "app.routes.templates.TemplateService.create",
        new_callable=AsyncMock,
        return_value=template,
    ):
        resp = client.post("/api/v1/templates/", json=data)
    assert resp.status_code == 201
    body = resp.json()
    assert body["data"]["name"] == "Customer Support Bot"
    assert "meta" in body


def test_create_template_missing_required_field(client: TestClient) -> None:
    """POST /api/v1/templates/ returns 422 when required fields missing."""
    resp = client.post("/api/v1/templates/", json={"name": "Incomplete"})
    assert resp.status_code == 422


# ── Get template ────────────────────────────────────────────────────


def test_get_template(client: TestClient) -> None:
    """GET /api/v1/templates/{id} returns envelope with template data."""
    template = _sample_template()
    with patch(
        "app.routes.templates.TemplateService.get",
        new_callable=AsyncMock,
        return_value=template,
    ):
        resp = client.get(f"/api/v1/templates/{TEMPLATE_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["id"] == str(TEMPLATE_ID)
    assert body["data"]["category"] == "customer_support"
    assert "meta" in body


def test_get_template_not_found(client: TestClient) -> None:
    """GET /api/v1/templates/{id} returns 404 when template doesn't exist."""
    with patch(
        "app.routes.templates.TemplateService.get",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.get(f"/api/v1/templates/{TEMPLATE_ID}")
    assert resp.status_code == 404


# ── Update template ─────────────────────────────────────────────────


def test_update_template(client: TestClient) -> None:
    """PUT /api/v1/templates/{id} returns envelope with updated template."""
    updated = _sample_template(name="Renamed Template")
    with patch(
        "app.routes.templates.TemplateService.update",
        new_callable=AsyncMock,
        return_value=updated,
    ):
        resp = client.put(
            f"/api/v1/templates/{TEMPLATE_ID}",
            json={"name": "Renamed Template"},
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "Renamed Template"


def test_update_template_not_found(client: TestClient) -> None:
    """PUT /api/v1/templates/{id} returns 404 when template doesn't exist."""
    with patch(
        "app.routes.templates.TemplateService.update",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.put(
            f"/api/v1/templates/{TEMPLATE_ID}",
            json={"name": "Renamed"},
        )
    assert resp.status_code == 404


# ── Delete template ─────────────────────────────────────────────────


def test_delete_template(client: TestClient) -> None:
    """DELETE /api/v1/templates/{id} returns 204 on success."""
    with patch(
        "app.routes.templates.TemplateService.delete",
        new_callable=AsyncMock,
        return_value=True,
    ):
        resp = client.delete(f"/api/v1/templates/{TEMPLATE_ID}")
    assert resp.status_code == 204


def test_delete_template_not_found(client: TestClient) -> None:
    """DELETE /api/v1/templates/{id} returns 404 when template doesn't exist."""
    with patch(
        "app.routes.templates.TemplateService.delete",
        new_callable=AsyncMock,
        return_value=False,
    ):
        resp = client.delete(f"/api/v1/templates/{TEMPLATE_ID}")
    assert resp.status_code == 404


# ── Instantiate template ────────────────────────────────────────────


def test_instantiate_template(client: TestClient) -> None:
    """POST /api/v1/templates/{id}/instantiate returns 201 with new agent."""
    agent = Agent(
        id=AGENT_ID,
        name="Customer Support Bot (from template)",
        description="A chatbot template for customer support",
        definition={"model": "gpt-4", "nodes": [], "edges": []},
        status="draft",
        owner_id=OWNER_ID,
        tags=["chatbot", "support"],
        created_at=NOW,
        updated_at=NOW,
    )
    with patch(
        "app.routes.templates.TemplateService.instantiate",
        new_callable=AsyncMock,
        return_value=agent,
    ):
        resp = client.post(
            f"/api/v1/templates/{TEMPLATE_ID}/instantiate",
            json={"owner_id": str(OWNER_ID)},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["data"]["name"] == "Customer Support Bot (from template)"
    assert body["data"]["status"] == "draft"
    assert "meta" in body


def test_instantiate_template_not_found(client: TestClient) -> None:
    """POST /api/v1/templates/{id}/instantiate returns 404 when not found."""
    with patch(
        "app.routes.templates.TemplateService.instantiate",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.post(
            f"/api/v1/templates/{TEMPLATE_ID}/instantiate",
            json={"owner_id": str(OWNER_ID)},
        )
    assert resp.status_code == 404


def test_instantiate_template_missing_owner(client: TestClient) -> None:
    """POST /api/v1/templates/{id}/instantiate returns 422 without owner_id."""
    resp = client.post(
        f"/api/v1/templates/{TEMPLATE_ID}/instantiate",
        json={},
    )
    assert resp.status_code == 422


# ── Edge cases ──────────────────────────────────────────────────────


def test_list_templates_empty(client: TestClient) -> None:
    """GET /api/v1/templates/ returns empty data list when no templates exist."""
    with patch(
        "app.routes.templates.TemplateService.list",
        new_callable=AsyncMock,
        return_value=([], 0),
    ):
        resp = client.get("/api/v1/templates/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["meta"]["pagination"]["total"] == 0


def test_list_templates_invalid_limit(client: TestClient) -> None:
    """GET /api/v1/templates/?limit=0 returns 422 for invalid limit."""
    resp = client.get("/api/v1/templates/?limit=0")
    assert resp.status_code == 422


def test_list_templates_limit_too_large(client: TestClient) -> None:
    """GET /api/v1/templates/?limit=200 returns 422 for exceeding max."""
    resp = client.get("/api/v1/templates/?limit=200")
    assert resp.status_code == 422


def test_create_template_with_all_fields(client: TestClient) -> None:
    """POST /api/v1/templates/ with all optional fields set."""
    template = _sample_template(is_featured=True)
    data = _sample_template_data(is_featured=True)
    with patch(
        "app.routes.templates.TemplateService.create",
        new_callable=AsyncMock,
        return_value=template,
    ):
        resp = client.post("/api/v1/templates/", json=data)
    assert resp.status_code == 201
    assert resp.json()["data"]["is_featured"] is True


def test_get_template_invalid_uuid(client: TestClient) -> None:
    """GET /api/v1/templates/not-a-uuid returns 422."""
    resp = client.get("/api/v1/templates/not-a-uuid")
    assert resp.status_code == 422


def test_update_template_partial(client: TestClient) -> None:
    """PUT /api/v1/templates/{id} with only description updates correctly."""
    updated = _sample_template(description="Updated description")
    with patch(
        "app.routes.templates.TemplateService.update",
        new_callable=AsyncMock,
        return_value=updated,
    ) as mock_update:
        resp = client.put(
            f"/api/v1/templates/{TEMPLATE_ID}",
            json={"description": "Updated description"},
        )
    assert resp.status_code == 200
    # Verify only description was sent to service (exclude_unset)
    call_data = mock_update.call_args[0][2]
    assert "description" in call_data
    assert "name" not in call_data
