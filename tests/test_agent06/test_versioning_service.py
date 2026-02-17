"""Tests for the enterprise VersioningService.

Covers create_version (signed), diff_versions (secrets-aware),
rollback (compatible/incompatible), promote, verify_signature,
tenant isolation, and mocked SecretsManager / DB interactions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.versioning import (
    AgentVersion,
    DeploymentPromotion,
    RollbackPreFlight,
    SignatureVerification,
    VersionDiff,
)
from app.services.versioning_service import (
    VersioningService,
    _bump_version,
    _canonical_json,
    _compute_hash,
    _extract_secret_paths,
    _sign,
)


# ── Fixtures ────────────────────────────────────────────────────────


def _make_user(
    tenant_id: str = "tenant-1",
    roles: list[str] | None = None,
    user_id: str | None = None,
) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user_id or str(uuid4()),
        email="dev@example.com",
        tenant_id=tenant_id,
        roles=roles or ["admin"],
        permissions=[],
    )


def _make_agent_version_db(
    agent_id: UUID | None = None,
    version: str = "1.0.0",
    definition: dict[str, Any] | None = None,
    change_log: str = "initial",
    created_by: UUID | None = None,
) -> MagicMock:
    """Build a mock AgentVersionDB row."""
    mock = MagicMock()
    mock.id = uuid4()
    mock.agent_id = agent_id or uuid4()
    mock.version = version
    mock.definition = definition or {"nodes": {"a": {"type": "llm"}}}
    mock.change_log = change_log
    mock.created_by = created_by or uuid4()
    mock.created_at = datetime.now(tz=timezone.utc)
    return mock


def _make_agent_db(
    agent_id: UUID | None = None,
    definition: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a mock Agent DB row."""
    mock = MagicMock()
    mock.id = agent_id or uuid4()
    mock.definition = definition or {"nodes": {"a": {"type": "llm"}}}
    return mock


def _mock_secrets() -> AsyncMock:
    sm = AsyncMock()
    sm.get_secret = AsyncMock(return_value={"key": "test-signing-key"})
    return sm


def _mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


# ── Helper unit tests ───────────────────────────────────────────────


def test_bump_version_none() -> None:
    """First version starts at 1.0.0."""
    assert _bump_version(None) == "1.0.0"


def test_bump_version_increments_patch() -> None:
    """Patch component is incremented."""
    assert _bump_version("1.0.0") == "1.0.1"
    assert _bump_version("2.3.9") == "2.3.10"


def test_canonical_json_deterministic() -> None:
    """canonical JSON is deterministic regardless of key order."""
    a = _canonical_json({"b": 2, "a": 1})
    b = _canonical_json({"a": 1, "b": 2})
    assert a == b


def test_compute_hash_reproducible() -> None:
    """SHA-256 hash is reproducible."""
    h1 = _compute_hash("hello")
    h2 = _compute_hash("hello")
    assert h1 == h2 and len(h1) == 64


def test_sign_produces_hmac() -> None:
    """_sign produces a valid HMAC hex string."""
    sig = _sign("abc123", "mykey")
    assert len(sig) == 64  # SHA-256 hex


def test_extract_secret_paths_nested() -> None:
    """Secret paths are extracted from nested definitions."""
    defn = {
        "nodes": {
            "n1": {"secret_path": "vault/a"},
            "n2": {"config": {"vault_path": "vault/b"}},
        }
    }
    paths = _extract_secret_paths(defn)
    assert paths == {"vault/a", "vault/b"}


def test_extract_secret_paths_empty() -> None:
    """No secret paths from plain definitions."""
    assert _extract_secret_paths({"nodes": {"a": {"type": "llm"}}}) == set()


# ── create_version ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_version_success() -> None:
    """create_version returns a signed AgentVersion."""
    user = _make_user()
    agent_id = uuid4()
    agent_db = _make_agent_db(agent_id=agent_id)
    session = _mock_session()
    secrets = _mock_secrets()

    # Mock select(Agent) → agent_db
    exec_result = MagicMock()
    exec_result.first.return_value = agent_db
    session.exec = AsyncMock(return_value=exec_result)

    # Mock _latest_version → None (first version)
    with patch("app.services.versioning_service._latest_version", new_callable=AsyncMock) as mock_latest:
        mock_latest.return_value = None
        version = await VersioningService.create_version(
            tenant_id="tenant-1",
            user=user,
            agent_id=agent_id,
            change_reason="initial release",
            session=session,
            secrets=secrets,
        )

    assert version.version_number == "1.0.0"
    assert version.signature != ""
    assert version.content_hash != ""
    assert version.signing_identity == user.email
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_version_rbac_denied() -> None:
    """Viewer users cannot create versions."""
    viewer = _make_user(roles=["viewer"])
    session = _mock_session()
    secrets = _mock_secrets()

    with pytest.raises(PermissionError, match="Insufficient permissions"):
        await VersioningService.create_version(
            tenant_id="tenant-1",
            user=viewer,
            agent_id=uuid4(),
            change_reason="nope",
            session=session,
            secrets=secrets,
        )


@pytest.mark.asyncio
async def test_create_version_agent_not_found() -> None:
    """ValueError when agent does not exist."""
    user = _make_user()
    session = _mock_session()
    secrets = _mock_secrets()
    exec_result = MagicMock()
    exec_result.first.return_value = None
    session.exec = AsyncMock(return_value=exec_result)

    with pytest.raises(ValueError, match="not found"):
        await VersioningService.create_version(
            tenant_id="tenant-1",
            user=user,
            agent_id=uuid4(),
            change_reason="test",
            session=session,
            secrets=secrets,
        )


@pytest.mark.asyncio
async def test_create_version_increments() -> None:
    """Second version bumps to 1.0.1."""
    user = _make_user()
    agent_id = uuid4()
    agent_db = _make_agent_db(agent_id=agent_id)
    session = _mock_session()
    secrets = _mock_secrets()

    exec_result = MagicMock()
    exec_result.first.return_value = agent_db
    session.exec = AsyncMock(return_value=exec_result)

    latest_mock = MagicMock()
    latest_mock.version = "1.0.0"

    with patch("app.services.versioning_service._latest_version", new_callable=AsyncMock) as mock_latest:
        mock_latest.return_value = latest_mock
        version = await VersioningService.create_version(
            tenant_id="tenant-1",
            user=user,
            agent_id=agent_id,
            change_reason="bugfix",
            session=session,
            secrets=secrets,
        )

    assert version.version_number == "1.0.1"


# ── diff_versions ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_diff_versions_shows_changes() -> None:
    """Diff detects added, removed, and modified nodes."""
    agent_id = uuid4()
    va = _make_agent_version_db(
        agent_id=agent_id,
        definition={"nodes": {"a": {"type": "llm"}, "b": {"type": "tool"}}},
    )
    vb = _make_agent_version_db(
        agent_id=agent_id,
        definition={"nodes": {"a": {"type": "llm-v2"}, "c": {"type": "retriever"}}},
    )
    session = _mock_session()
    session.get = AsyncMock(side_effect=lambda cls, vid: va if vid == va.id else vb)

    diff = await VersioningService.diff_versions(
        tenant_id="tenant-1",
        version_a_id=va.id,
        version_b_id=vb.id,
        session=session,
    )
    assert "c" in diff.nodes_added
    assert "b" in diff.nodes_removed
    assert any(m["node"] == "a" for m in diff.nodes_modified)


@pytest.mark.asyncio
async def test_diff_versions_secrets_aware() -> None:
    """Diff shows secret path additions/removals without values."""
    agent_id = uuid4()
    va = _make_agent_version_db(
        agent_id=agent_id,
        definition={"nodes": {}, "secret_path": "vault/old"},
    )
    vb = _make_agent_version_db(
        agent_id=agent_id,
        definition={"nodes": {}, "secret_path": "vault/new"},
    )
    session = _mock_session()
    session.get = AsyncMock(side_effect=lambda cls, vid: va if vid == va.id else vb)

    diff = await VersioningService.diff_versions(
        "tenant-1", va.id, vb.id, session=session,
    )
    assert "vault/new" in diff.secrets_paths_added
    assert "vault/old" in diff.secrets_paths_removed


@pytest.mark.asyncio
async def test_diff_versions_not_found() -> None:
    """ValueError when a version doesn't exist."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="not found"):
        await VersioningService.diff_versions(
            "tenant-1", uuid4(), uuid4(), session=session,
        )


@pytest.mark.asyncio
async def test_diff_versions_different_agents() -> None:
    """Cannot diff versions belonging to different agents."""
    va = _make_agent_version_db(agent_id=uuid4())
    vb = _make_agent_version_db(agent_id=uuid4())
    session = _mock_session()
    session.get = AsyncMock(side_effect=lambda cls, vid: va if vid == va.id else vb)

    with pytest.raises(ValueError, match="different agents"):
        await VersioningService.diff_versions(
            "tenant-1", va.id, vb.id, session=session,
        )


# ── rollback ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rollback_success() -> None:
    """Rollback creates a new version from the target snapshot."""
    user = _make_user()
    agent_id = uuid4()
    target = _make_agent_version_db(agent_id=agent_id, version="1.0.0")
    session = _mock_session()
    secrets = _mock_secrets()

    session.get = AsyncMock(return_value=target)

    latest_mock = MagicMock()
    latest_mock.version = "1.0.2"

    with patch("app.services.versioning_service._latest_version", new_callable=AsyncMock) as mock_latest:
        mock_latest.return_value = latest_mock
        result = await VersioningService.rollback(
            tenant_id="tenant-1",
            user=user,
            agent_id=agent_id,
            target_version_id=target.id,
            session=session,
            secrets=secrets,
        )

    assert result.version_number == "1.0.3"
    assert "Rollback" in result.change_reason
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_rollback_incompatible_secrets() -> None:
    """Rollback proceeds with warnings when secrets are unavailable."""
    user = _make_user()
    agent_id = uuid4()
    target = _make_agent_version_db(
        agent_id=agent_id,
        definition={"nodes": {}, "secret_path": "vault/missing"},
    )
    session = _mock_session()
    secrets = _mock_secrets()
    secrets.get_secret = AsyncMock(side_effect=Exception("not found"))

    session.get = AsyncMock(return_value=target)

    with patch("app.services.versioning_service._latest_version", new_callable=AsyncMock) as mock_latest:
        mock_latest.return_value = None
        result = await VersioningService.rollback(
            tenant_id="tenant-1",
            user=user,
            agent_id=agent_id,
            target_version_id=target.id,
            session=session,
            secrets=secrets,
        )

    assert result.version_number == "1.0.0"


@pytest.mark.asyncio
async def test_rollback_rbac_denied() -> None:
    """Viewers cannot perform rollback."""
    viewer = _make_user(roles=["viewer"])
    session = _mock_session()
    secrets = _mock_secrets()

    with pytest.raises(PermissionError, match="Insufficient permissions"):
        await VersioningService.rollback(
            tenant_id="tenant-1",
            user=viewer,
            agent_id=uuid4(),
            target_version_id=uuid4(),
            session=session,
            secrets=secrets,
        )


@pytest.mark.asyncio
async def test_rollback_target_not_found() -> None:
    """ValueError when target version doesn't exist."""
    user = _make_user()
    session = _mock_session()
    secrets = _mock_secrets()
    session.get = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="not found"):
        await VersioningService.rollback(
            tenant_id="tenant-1",
            user=user,
            agent_id=uuid4(),
            target_version_id=uuid4(),
            session=session,
            secrets=secrets,
        )


@pytest.mark.asyncio
async def test_rollback_wrong_agent() -> None:
    """ValueError when target version belongs to a different agent."""
    user = _make_user()
    target = _make_agent_version_db(agent_id=uuid4())
    session = _mock_session()
    secrets = _mock_secrets()
    session.get = AsyncMock(return_value=target)

    with pytest.raises(ValueError, match="does not belong"):
        await VersioningService.rollback(
            tenant_id="tenant-1",
            user=user,
            agent_id=uuid4(),
            target_version_id=target.id,
            session=session,
            secrets=secrets,
        )


# ── promote ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_promote_dev_to_staging() -> None:
    """Promotion from development to staging succeeds."""
    user = _make_user()
    version_db = _make_agent_version_db(
        definition={"_environment": "development", "nodes": {}},
        change_log="ready",
    )
    session = _mock_session()
    session.get = AsyncMock(return_value=version_db)

    promo = await VersioningService.promote(
        tenant_id="tenant-1",
        user=user,
        version_id=version_db.id,
        target_env="staging",
        session=session,
    )
    assert promo.status == "promoted"
    assert promo.source_env == "development"
    assert promo.target_env == "staging"


@pytest.mark.asyncio
async def test_promote_invalid_env() -> None:
    """ValueError for unknown target environment."""
    user = _make_user()
    session = _mock_session()

    with pytest.raises(ValueError, match="Invalid environment"):
        await VersioningService.promote(
            "tenant-1", user, uuid4(), "canary", session=session,
        )


@pytest.mark.asyncio
async def test_promote_skip_env_rejected() -> None:
    """Cannot skip from development directly to production."""
    user = _make_user()
    version_db = _make_agent_version_db(
        definition={"_environment": "development", "nodes": {}},
    )
    session = _mock_session()
    session.get = AsyncMock(return_value=version_db)

    with pytest.raises(ValueError, match="Cannot promote"):
        await VersioningService.promote(
            "tenant-1", user, version_db.id, "production", session=session,
        )


@pytest.mark.asyncio
async def test_promote_production_requires_changelog() -> None:
    """Production promotion requires a change reason."""
    user = _make_user()
    version_db = _make_agent_version_db(
        definition={"_environment": "staging", "nodes": {}},
        change_log="",
    )
    version_db.change_log = ""
    session = _mock_session()
    session.get = AsyncMock(return_value=version_db)

    with pytest.raises(ValueError, match="Change reason required"):
        await VersioningService.promote(
            "tenant-1", user, version_db.id, "production", session=session,
        )


@pytest.mark.asyncio
async def test_promote_rbac_denied() -> None:
    """Viewers cannot promote versions."""
    viewer = _make_user(roles=["viewer"])
    session = _mock_session()

    with pytest.raises(PermissionError, match="Insufficient permissions"):
        await VersioningService.promote(
            "tenant-1", viewer, uuid4(), "staging", session=session,
        )


# ── verify_signature ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_signature_valid() -> None:
    """Signature verification returns valid=True."""
    version_db = _make_agent_version_db()
    session = _mock_session()
    secrets = _mock_secrets()
    session.get = AsyncMock(return_value=version_db)

    result = await VersioningService.verify_signature(
        version_id=version_db.id,
        session=session,
        secrets=secrets,
        tenant_id="tenant-1",
    )
    assert result.valid is True
    assert result.content_hash_matches is True


@pytest.mark.asyncio
async def test_verify_signature_not_found() -> None:
    """ValueError when version doesn't exist."""
    session = _mock_session()
    secrets = _mock_secrets()
    session.get = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="not found"):
        await VersioningService.verify_signature(
            version_id=uuid4(),
            session=session,
            secrets=secrets,
            tenant_id="tenant-1",
        )


# ── Tenant isolation ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_isolation_create_version() -> None:
    """Version is created under the correct tenant context."""
    user_t1 = _make_user(tenant_id="t1")
    agent_id = uuid4()
    agent_db = _make_agent_db(agent_id=agent_id)
    session = _mock_session()
    secrets = _mock_secrets()

    exec_result = MagicMock()
    exec_result.first.return_value = agent_db
    session.exec = AsyncMock(return_value=exec_result)

    with patch("app.services.versioning_service._latest_version", new_callable=AsyncMock) as mock_latest:
        mock_latest.return_value = None
        version = await VersioningService.create_version(
            tenant_id="t1",
            user=user_t1,
            agent_id=agent_id,
            change_reason="t1 release",
            session=session,
            secrets=secrets,
        )

    # Verify secrets were fetched with correct tenant
    secrets.get_secret.assert_awaited_once_with("platform/signing-key", "t1")


@pytest.mark.asyncio
async def test_signing_key_fallback() -> None:
    """Fallback signing key used when Vault is unreachable."""
    user = _make_user()
    agent_id = uuid4()
    agent_db = _make_agent_db(agent_id=agent_id)
    session = _mock_session()
    secrets = _mock_secrets()
    secrets.get_secret = AsyncMock(side_effect=Exception("vault unreachable"))

    exec_result = MagicMock()
    exec_result.first.return_value = agent_db
    session.exec = AsyncMock(return_value=exec_result)

    with patch("app.services.versioning_service._latest_version", new_callable=AsyncMock) as mock_latest:
        mock_latest.return_value = None
        version = await VersioningService.create_version(
            tenant_id="tenant-1",
            user=user,
            agent_id=agent_id,
            change_reason="fallback test",
            session=session,
            secrets=secrets,
        )

    assert version.signature != ""
    assert version.version_number == "1.0.0"
