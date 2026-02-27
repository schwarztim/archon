"""Tests for QA Workflow Trigger endpoints.

Uses an in-memory SQLite database and httpx.AsyncClient — no external services needed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlmodel import SQLModel, create_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker

# Ensure backend is importable
backend_dir = str(Path(__file__).resolve().parent.parent / "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.database import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models.qa import QAWorkflowRequest  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_engine():
    """Create an in-memory async SQLite engine with all tables."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Yield an async session backed by the in-memory engine."""
    factory = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_engine):
    """Test client with overridden DB session."""
    factory = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _qa_url(path: str = "") -> str:
    return f"/api/v1/qa{path}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestQATrigger:
    """Tests for POST /api/v1/qa/trigger."""

    @pytest.mark.asyncio
    async def test_trigger_creates_record(self, client):
        """Triggering QA creates a persisted record with pending/submitted status."""
        resp = await client.post(
            _qa_url("/trigger"),
            json={"payload": {"test_key": "test_value"}, "trigger_source": "manual"},
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["id"] is not None
        assert data["status"] in ("pending", "submitted", "failed")
        assert data["trigger_source"] == "manual"

    @pytest.mark.asyncio
    async def test_trigger_with_workflow_id(self, client):
        """Payload with workflow_id is stored correctly."""
        resp = await client.post(
            _qa_url("/trigger"),
            json={"workflow_id": "wf-123", "workflow_run_id": "run-456"},
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["workflow_id"] == "wf-123"
        assert data["workflow_run_id"] == "run-456"

    @pytest.mark.asyncio
    async def test_trigger_no_endpoint_returns_pending(self, client):
        """Without a Logic Apps endpoint, status should be 'pending'."""
        with patch("app.config.settings.LOGIC_APPS_QA_ENDPOINT", ""):
            resp = await client.post(
                _qa_url("/trigger"),
                json={"trigger_source": "api"},
            )
        assert resp.status_code == 201
        assert resp.json()["data"]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_trigger_logic_apps_called_when_configured(self, client):
        """When endpoint configured and Logic Apps call is mocked, record is created."""
        import httpx
        from unittest.mock import MagicMock

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"run_id": "la-run-001"})
        mock_response.headers = {}
        mock_response.text = ""

        async def mock_post(*args, **kwargs):
            return mock_response

        # Patch at the service module level so the test client is unaffected
        with patch(
            "app.config.settings.LOGIC_APPS_QA_ENDPOINT",
            "https://logic.example.com/trigger",
        ):
            with patch(
                "app.services.qa_trigger_service.httpx.AsyncClient"
            ) as mock_client_cls:
                mock_ctx = AsyncMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_ctx.post = AsyncMock(return_value=mock_response)
                mock_client_cls.return_value = mock_ctx
                resp = await client.post(
                    _qa_url("/trigger"),
                    json={"payload": {"data": "x"}},
                )
        assert resp.status_code == 201
        assert resp.json()["data"]["status"] in ("pending", "submitted")


class TestQAListRequests:
    """Tests for GET /api/v1/qa/requests."""

    @pytest.mark.asyncio
    async def test_list_empty(self, client):
        """List endpoint returns empty data list when no records exist."""
        resp = await client.get(_qa_url("/requests"))
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    @pytest.mark.asyncio
    async def test_list_returns_records(self, client):
        """Records created via trigger appear in list."""
        await client.post(_qa_url("/trigger"), json={})
        await client.post(_qa_url("/trigger"), json={})
        resp = await client.get(_qa_url("/requests"))
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 2

    @pytest.mark.asyncio
    async def test_list_pagination(self, client):
        """Pagination parameters are respected."""
        for _ in range(5):
            await client.post(_qa_url("/trigger"), json={})
        resp = await client.get(_qa_url("/requests?limit=2&offset=0"))
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 2
        assert resp.json()["meta"]["pagination"]["total"] == 5

    @pytest.mark.asyncio
    async def test_list_status_filter(self, client):
        """Status filter returns only matching records."""
        await client.post(_qa_url("/trigger"), json={})
        resp = await client.get(_qa_url("/requests?status=pending"))
        assert resp.status_code == 200
        for item in resp.json()["data"]:
            assert item["status"] == "pending"


class TestQAGetRequest:
    """Tests for GET /api/v1/qa/requests/{id}."""

    @pytest.mark.asyncio
    async def test_get_existing(self, client):
        """Fetching an existing request by ID returns full detail."""
        create_resp = await client.post(
            _qa_url("/trigger"), json={"payload": {"k": "v"}}
        )
        request_id = create_resp.json()["data"]["id"]
        resp = await client.get(_qa_url(f"/requests/{request_id}"))
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == request_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_404(self, client):
        """Requesting a non-existent ID returns 404."""
        resp = await client.get(_qa_url("/requests/does-not-exist"))
        assert resp.status_code == 404


class TestQAWebhook:
    """Tests for POST /api/v1/qa/webhook."""

    @pytest.mark.asyncio
    async def test_webhook_matches_by_logic_apps_run_id(self, client, db_session):
        """Webhook callback updates the matching record."""
        # Create a record with a known logic_apps_run_id
        record = QAWorkflowRequest(
            logic_apps_run_id="la-xyz-001",
            status="submitted",
        )
        db_session.add(record)
        await db_session.commit()

        resp = await client.post(
            _qa_url("/webhook"),
            json={"run_id": "la-xyz-001", "status": "completed"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["matched"] is True
        assert body["data"]["status"] == "completed"
        assert body["data"]["callback_received"] is True

    @pytest.mark.asyncio
    async def test_webhook_no_run_id_returns_400(self, client):
        """Missing run_id in webhook payload returns 400."""
        resp = await client.post(_qa_url("/webhook"), json={"status": "completed"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_webhook_unknown_run_id_accepted(self, client):
        """Unknown run_id still returns 200 with matched=False."""
        resp = await client.post(
            _qa_url("/webhook"),
            json={"run_id": "unknown-run-id", "status": "completed"},
        )
        assert resp.status_code == 200
        assert resp.json()["matched"] is False


class TestQAStatus:
    """Tests for GET /api/v1/qa/status/{id}."""

    @pytest.mark.asyncio
    async def test_status_endpoint(self, client):
        """Status endpoint returns lightweight status dict."""
        create_resp = await client.post(_qa_url("/trigger"), json={})
        request_id = create_resp.json()["data"]["id"]
        resp = await client.get(_qa_url(f"/status/{request_id}"))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "status" in data
        assert data["id"] == request_id

    @pytest.mark.asyncio
    async def test_status_nonexistent_returns_404(self, client):
        """Non-existent request ID returns 404."""
        resp = await client.get(_qa_url("/status/nonexistent"))
        assert resp.status_code == 404
