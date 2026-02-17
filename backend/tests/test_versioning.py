"""Tests for the versioning system: service layer and route endpoints.

Covers version comparison (diff), rollback, and deployment promotion.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import get_session
from app.main import app
from app.models import AgentVersion
from app.services.agent_version_service import (
    AgentVersionService,
    _bump_patch,
    _diff_dicts,
    _parse_semver,
)

# ── Fixed UUIDs ─────────────────────────────────────────────────────

OWNER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
AGENT_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
VERSION_ID_1 = UUID("11111111-1111-1111-1111-111111111111")
VERSION_ID_2 = UUID("22222222-2222-2222-2222-222222222222")
NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _mock_session() -> AsyncMock:
    """Create a mock AsyncSession with standard ORM method stubs."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


# ═══════════════════════════════════════════════════════════════════
# Pure function tests — _diff_dicts, _parse_semver, _bump_patch
# ═══════════════════════════════════════════════════════════════════


class TestDiffDicts:
    """Tests for the _diff_dicts helper."""

    def test_identical_dicts(self) -> None:
        """Identical dicts produce no changes."""
        assert _diff_dicts({"a": 1}, {"a": 1}) == []

    def test_added_key(self) -> None:
        """New key in second dict is reported as added."""
        changes = _diff_dicts({}, {"key": "value"})
        assert len(changes) == 1
        assert changes[0]["type"] == "added"
        assert changes[0]["path"] == "key"
        assert changes[0]["new_value"] == "value"

    def test_removed_key(self) -> None:
        """Key missing from second dict is reported as removed."""
        changes = _diff_dicts({"key": "value"}, {})
        assert len(changes) == 1
        assert changes[0]["type"] == "removed"
        assert changes[0]["path"] == "key"
        assert changes[0]["old_value"] == "value"

    def test_changed_value(self) -> None:
        """Changed scalar value is reported correctly."""
        changes = _diff_dicts({"temp": 0.5}, {"temp": 0.9})
        assert len(changes) == 1
        assert changes[0]["type"] == "changed"
        assert changes[0]["old_value"] == 0.5
        assert changes[0]["new_value"] == 0.9

    def test_nested_dict_diff(self) -> None:
        """Nested dict changes are recursively tracked."""
        old = {"config": {"model": "gpt-4", "temp": 0.7}}
        new = {"config": {"model": "gpt-4o", "temp": 0.7}}
        changes = _diff_dicts(old, new)
        assert len(changes) == 1
        assert changes[0]["path"] == "config.model"
        assert changes[0]["type"] == "changed"

    def test_deeply_nested_diff(self) -> None:
        """Changes multiple levels deep are tracked with dotted paths."""
        old = {"a": {"b": {"c": 1}}}
        new = {"a": {"b": {"c": 2}}}
        changes = _diff_dicts(old, new)
        assert changes[0]["path"] == "a.b.c"

    def test_empty_dicts(self) -> None:
        """Two empty dicts produce no changes."""
        assert _diff_dicts({}, {}) == []

    def test_multiple_changes(self) -> None:
        """Multiple simultaneous changes are all reported."""
        old = {"a": 1, "b": 2, "c": 3}
        new = {"a": 1, "b": 99, "d": 4}
        changes = _diff_dicts(old, new)
        types = {c["path"]: c["type"] for c in changes}
        assert types == {"b": "changed", "c": "removed", "d": "added"}

    def test_type_change_not_recursive(self) -> None:
        """When a dict becomes a scalar, it reports a changed value, not recursion."""
        old = {"x": {"nested": 1}}
        new = {"x": "flat"}
        changes = _diff_dicts(old, new)
        assert len(changes) == 1
        assert changes[0]["type"] == "changed"
        assert changes[0]["old_value"] == {"nested": 1}
        assert changes[0]["new_value"] == "flat"


class TestSemverHelpers:
    """Tests for _parse_semver and _bump_patch."""

    def test_parse_full_semver(self) -> None:
        """Three-part semver is parsed correctly."""
        assert _parse_semver("1.2.3") == (1, 2, 3)

    def test_parse_major_only(self) -> None:
        """Single digit is treated as major.0.0."""
        assert _parse_semver("5") == (5, 0, 0)

    def test_parse_major_minor(self) -> None:
        """Two-part version fills patch with 0."""
        assert _parse_semver("2.1") == (2, 1, 0)

    def test_bump_patch(self) -> None:
        """Patch is incremented correctly."""
        assert _bump_patch("1.0.0") == "1.0.1"
        assert _bump_patch("2.3.9") == "2.3.10"


# ═══════════════════════════════════════════════════════════════════
# Service layer tests — AgentVersionService.compare
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_compare_success() -> None:
    """compare returns diff between two versions of the same agent."""
    session = _mock_session()

    v1 = AgentVersion(
        id=VERSION_ID_1, agent_id=AGENT_ID, version="1.0.0",
        definition={"model": "gpt-4", "temperature": 0.7},
        created_by=OWNER_ID,
    )
    v2 = AgentVersion(
        id=VERSION_ID_2, agent_id=AGENT_ID, version="1.0.1",
        definition={"model": "gpt-4o", "temperature": 0.7, "top_p": 0.9},
        created_by=OWNER_ID,
    )
    session.get = AsyncMock(side_effect=lambda cls, uid: v1 if uid == VERSION_ID_1 else v2)

    result = await AgentVersionService.compare(session, VERSION_ID_1, VERSION_ID_2)
    assert result["v1"]["version"] == "1.0.0"
    assert result["v2"]["version"] == "1.0.1"
    assert result["summary"]["total_changes"] == 2  # model changed, top_p added
    assert result["summary"]["added"] == 1
    assert result["summary"]["changed"] == 1


@pytest.mark.asyncio
async def test_compare_v1_not_found() -> None:
    """compare raises ValueError when first version is not found."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="not found"):
        await AgentVersionService.compare(session, VERSION_ID_1, VERSION_ID_2)


@pytest.mark.asyncio
async def test_compare_v2_not_found() -> None:
    """compare raises ValueError when second version is not found."""
    session = _mock_session()
    v1 = AgentVersion(
        id=VERSION_ID_1, agent_id=AGENT_ID, version="1.0.0",
        definition={}, created_by=OWNER_ID,
    )
    session.get = AsyncMock(side_effect=lambda cls, uid: v1 if uid == VERSION_ID_1 else None)

    with pytest.raises(ValueError, match="not found"):
        await AgentVersionService.compare(session, VERSION_ID_1, VERSION_ID_2)


@pytest.mark.asyncio
async def test_compare_different_agents() -> None:
    """compare raises ValueError when versions belong to different agents."""
    session = _mock_session()
    other_agent = uuid4()

    v1 = AgentVersion(
        id=VERSION_ID_1, agent_id=AGENT_ID, version="1.0.0",
        definition={}, created_by=OWNER_ID,
    )
    v2 = AgentVersion(
        id=VERSION_ID_2, agent_id=other_agent, version="1.0.0",
        definition={}, created_by=OWNER_ID,
    )
    session.get = AsyncMock(side_effect=lambda cls, uid: v1 if uid == VERSION_ID_1 else v2)

    with pytest.raises(ValueError, match="different agents"):
        await AgentVersionService.compare(session, VERSION_ID_1, VERSION_ID_2)


@pytest.mark.asyncio
async def test_compare_identical_versions() -> None:
    """compare returns zero changes for identical definitions."""
    session = _mock_session()
    defn = {"model": "gpt-4"}

    v1 = AgentVersion(
        id=VERSION_ID_1, agent_id=AGENT_ID, version="1.0.0",
        definition=defn, created_by=OWNER_ID,
    )
    v2 = AgentVersion(
        id=VERSION_ID_2, agent_id=AGENT_ID, version="1.0.1",
        definition=defn, created_by=OWNER_ID,
    )
    session.get = AsyncMock(side_effect=lambda cls, uid: v1 if uid == VERSION_ID_1 else v2)

    result = await AgentVersionService.compare(session, VERSION_ID_1, VERSION_ID_2)
    assert result["summary"]["total_changes"] == 0
    assert result["changes"] == []


# ═══════════════════════════════════════════════════════════════════
# Service layer tests — AgentVersionService.rollback
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rollback_success() -> None:
    """rollback creates a new version with the target's definition."""
    session = _mock_session()
    session.refresh = AsyncMock()

    target = AgentVersion(
        id=VERSION_ID_1, agent_id=AGENT_ID, version="1.0.0",
        definition={"model": "gpt-4"}, created_by=OWNER_ID,
    )
    latest = AgentVersion(
        id=VERSION_ID_2, agent_id=AGENT_ID, version="2.0.0",
        definition={"model": "gpt-4o"}, created_by=OWNER_ID,
    )
    session.get = AsyncMock(return_value=target)

    # Mock get_latest via exec
    exec_result = MagicMock()
    exec_result.first.return_value = latest
    session.exec = AsyncMock(return_value=exec_result)

    result = await AgentVersionService.rollback(
        session, agent_id=AGENT_ID, target_version_id=VERSION_ID_1, created_by=OWNER_ID,
    )

    assert result.definition == {"model": "gpt-4"}
    assert result.version == "2.0.1"
    assert "Rollback" in (result.change_log or "")
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_rollback_target_not_found() -> None:
    """rollback raises ValueError when target version is not found."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="not found"):
        await AgentVersionService.rollback(
            session, agent_id=AGENT_ID, target_version_id=VERSION_ID_1, created_by=OWNER_ID,
        )


@pytest.mark.asyncio
async def test_rollback_wrong_agent() -> None:
    """rollback raises ValueError when target version belongs to a different agent."""
    session = _mock_session()
    other_agent = uuid4()

    target = AgentVersion(
        id=VERSION_ID_1, agent_id=other_agent, version="1.0.0",
        definition={}, created_by=OWNER_ID,
    )
    session.get = AsyncMock(return_value=target)

    with pytest.raises(ValueError, match="does not belong"):
        await AgentVersionService.rollback(
            session, agent_id=AGENT_ID, target_version_id=VERSION_ID_1, created_by=OWNER_ID,
        )


# ═══════════════════════════════════════════════════════════════════
# Service layer tests — AgentVersionService.promote
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_promote_success() -> None:
    """promote creates a new version with the target environment set."""
    session = _mock_session()
    session.refresh = AsyncMock()

    source = AgentVersion(
        id=VERSION_ID_1, agent_id=AGENT_ID, version="1.0.0",
        definition={"model": "gpt-4", "_environment": "development"},
        created_by=OWNER_ID,
    )
    session.get = AsyncMock(return_value=source)

    exec_result = MagicMock()
    exec_result.first.return_value = source
    session.exec = AsyncMock(return_value=exec_result)

    result = await AgentVersionService.promote(
        session, version_id=VERSION_ID_1,
        target_environment="staging", created_by=OWNER_ID,
    )

    assert result.definition["_environment"] == "staging"
    assert "Promoted" in (result.change_log or "")
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_promote_invalid_environment() -> None:
    """promote raises ValueError for invalid environment."""
    session = _mock_session()

    with pytest.raises(ValueError, match="Invalid environment"):
        await AgentVersionService.promote(
            session, version_id=VERSION_ID_1,
            target_environment="invalid", created_by=OWNER_ID,
        )


@pytest.mark.asyncio
async def test_promote_version_not_found() -> None:
    """promote raises ValueError when version is not found."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="not found"):
        await AgentVersionService.promote(
            session, version_id=VERSION_ID_1,
            target_environment="staging", created_by=OWNER_ID,
        )


@pytest.mark.asyncio
async def test_promote_wrong_order() -> None:
    """promote raises ValueError when skipping promotion pipeline."""
    session = _mock_session()

    source = AgentVersion(
        id=VERSION_ID_1, agent_id=AGENT_ID, version="1.0.0",
        definition={"model": "gpt-4", "_environment": "development"},
        created_by=OWNER_ID,
    )
    session.get = AsyncMock(return_value=source)

    with pytest.raises(ValueError, match="Cannot promote"):
        await AgentVersionService.promote(
            session, version_id=VERSION_ID_1,
            target_environment="production", created_by=OWNER_ID,
        )


# ═══════════════════════════════════════════════════════════════════
# Route integration tests — compare endpoint
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture()
def client() -> TestClient:
    """FastAPI TestClient with the DB session dependency overridden."""
    mock_session = _mock_session()

    v1 = AgentVersion(
        id=VERSION_ID_1, agent_id=AGENT_ID, version="1.0.0",
        definition={"model": "gpt-4", "temperature": 0.7},
        created_by=OWNER_ID, created_at=NOW,
    )
    v2 = AgentVersion(
        id=VERSION_ID_2, agent_id=AGENT_ID, version="1.0.1",
        definition={"model": "gpt-4o", "temperature": 0.7},
        created_by=OWNER_ID, created_at=NOW,
    )

    async def _get(cls: type, uid: UUID) -> AgentVersion | None:
        if uid == VERSION_ID_1:
            return v1
        if uid == VERSION_ID_2:
            return v2
        return None

    mock_session.get = AsyncMock(side_effect=_get)
    mock_session.refresh = AsyncMock()

    exec_result = MagicMock()
    exec_result.first.return_value = v2
    mock_session.exec = AsyncMock(return_value=exec_result)

    async def _override_session():  # noqa: ANN202
        yield mock_session

    app.dependency_overrides[get_session] = _override_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_compare_route_success(client: TestClient) -> None:
    """GET /api/v1/agents/{id}/versions/compare returns diff."""
    resp = client.get(
        f"/api/v1/agents/{AGENT_ID}/versions/compare",
        params={"v1": str(VERSION_ID_1), "v2": str(VERSION_ID_2)},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["summary"]["total_changes"] == 1
    assert data["summary"]["changed"] == 1


def test_compare_route_version_not_found(client: TestClient) -> None:
    """GET compare returns 404 when a version does not exist."""
    missing_id = uuid4()
    resp = client.get(
        f"/api/v1/agents/{AGENT_ID}/versions/compare",
        params={"v1": str(missing_id), "v2": str(VERSION_ID_2)},
    )
    assert resp.status_code == 404


def test_compare_route_wrong_agent(client: TestClient) -> None:
    """GET compare returns 400 when versions don't belong to the agent in path."""
    wrong_agent = uuid4()
    resp = client.get(
        f"/api/v1/agents/{wrong_agent}/versions/compare",
        params={"v1": str(VERSION_ID_1), "v2": str(VERSION_ID_2)},
    )
    assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════
# Route integration tests — rollback endpoint
# ═══════════════════════════════════════════════════════════════════


def test_rollback_route_success(client: TestClient) -> None:
    """POST rollback returns 201 with the new version."""
    resp = client.post(
        f"/api/v1/agents/{AGENT_ID}/versions/{VERSION_ID_1}/rollback",
        json={"created_by": str(OWNER_ID)},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["definition"]["model"] == "gpt-4"
    assert "Rollback" in data["change_log"]


def test_rollback_route_not_found() -> None:
    """POST rollback returns 404 for a missing version."""
    mock_session = _mock_session()
    mock_session.get = AsyncMock(return_value=None)

    async def _override():  # noqa: ANN202
        yield mock_session

    app.dependency_overrides[get_session] = _override
    c = TestClient(app)

    missing = uuid4()
    resp = c.post(
        f"/api/v1/agents/{AGENT_ID}/versions/{missing}/rollback",
        json={"created_by": str(OWNER_ID)},
    )
    assert resp.status_code == 404
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════
# Route integration tests — promote endpoint
# ═══════════════════════════════════════════════════════════════════


def test_promote_route_success(client: TestClient) -> None:
    """POST promote returns 201 with the promoted version."""
    resp = client.post(
        f"/api/v1/agents/{AGENT_ID}/versions/{VERSION_ID_1}/promote",
        json={"target_environment": "staging", "created_by": str(OWNER_ID)},
    )
    # The fixture version has no _environment, so default is 'development' → staging is valid
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["definition"]["_environment"] == "staging"


def test_promote_route_invalid_env(client: TestClient) -> None:
    """POST promote returns 400 for an invalid environment name."""
    resp = client.post(
        f"/api/v1/agents/{AGENT_ID}/versions/{VERSION_ID_1}/promote",
        json={"target_environment": "unknown", "created_by": str(OWNER_ID)},
    )
    assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════
# Response envelope tests
# ═══════════════════════════════════════════════════════════════════


def test_compare_response_envelope(client: TestClient) -> None:
    """Compare response follows standard envelope format."""
    resp = client.get(
        f"/api/v1/agents/{AGENT_ID}/versions/compare",
        params={"v1": str(VERSION_ID_1), "v2": str(VERSION_ID_2)},
    )
    body = resp.json()
    assert "data" in body
    assert "meta" in body
    assert "request_id" in body["meta"]
    assert "timestamp" in body["meta"]


def test_rollback_response_envelope(client: TestClient) -> None:
    """Rollback response follows standard envelope format."""
    resp = client.post(
        f"/api/v1/agents/{AGENT_ID}/versions/{VERSION_ID_1}/rollback",
        json={"created_by": str(OWNER_ID)},
    )
    body = resp.json()
    assert "data" in body
    assert "meta" in body
    assert "request_id" in body["meta"]
    assert "timestamp" in body["meta"]
