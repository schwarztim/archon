"""Unit tests for ModelRegistry and RoutingRuleService CRUD operations.

Each method is tested by mocking the session's ORM calls
(get, exec, add, commit, refresh, delete) to verify service logic
without requiring a real database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.models.router import ModelRegistryEntry, RoutingRule
from app.services.router import ModelRegistry, RoutingRuleService

# ── Fixed UUIDs for deterministic tests ─────────────────────────────

MODEL_ID = UUID("11111111-1111-1111-1111-111111111111")
MODEL_ID_2 = UUID("22222222-2222-2222-2222-222222222222")
RULE_ID = UUID("33333333-3333-3333-3333-333333333333")
AGENT_ID = UUID("44444444-4444-4444-4444-444444444444")
DEPT_ID = UUID("55555555-5555-5555-5555-555555555555")
NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ── Helpers ─────────────────────────────────────────────────────────


def _mock_session() -> AsyncMock:
    """Create a mock AsyncSession with standard ORM method stubs."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


def _make_model(
    *,
    model_id: UUID = MODEL_ID,
    name: str = "gpt-4o",
    provider: str = "openai",
    capabilities: list[str] | None = None,
    is_active: bool = True,
    health_status: str = "healthy",
    cost_per_input_token: float = 5.0,
    cost_per_output_token: float = 15.0,
    avg_latency_ms: float = 400.0,
    data_classification: str = "general",
    is_on_prem: bool = False,
) -> ModelRegistryEntry:
    """Build a ModelRegistryEntry with sensible defaults."""
    return ModelRegistryEntry(
        id=model_id,
        name=name,
        provider=provider,
        model_id=f"{provider}-{name}",
        capabilities=["chat", "code"] if capabilities is None else capabilities,
        context_window=128_000,
        supports_streaming=True,
        cost_per_input_token=cost_per_input_token,
        cost_per_output_token=cost_per_output_token,
        speed_tier="fast",
        avg_latency_ms=avg_latency_ms,
        data_classification=data_classification,
        is_on_prem=is_on_prem,
        is_active=is_active,
        health_status=health_status,
        error_rate=0.0,
        config={},
        created_at=NOW,
        updated_at=NOW,
    )


def _make_rule(
    *,
    rule_id: UUID = RULE_ID,
    name: str = "default-rule",
    strategy: str = "balanced",
    priority: int = 10,
    is_active: bool = True,
    department_id: UUID | None = None,
    agent_id: UUID | None = None,
) -> RoutingRule:
    """Build a RoutingRule with sensible defaults."""
    return RoutingRule(
        id=rule_id,
        name=name,
        strategy=strategy,
        priority=priority,
        is_active=is_active,
        department_id=department_id,
        agent_id=agent_id,
        weight_cost=0.25,
        weight_latency=0.25,
        weight_capability=0.25,
        weight_sensitivity=0.25,
        conditions={},
        fallback_chain=[],
        created_at=NOW,
        updated_at=NOW,
    )


# ═══════════════════════════════════════════════════════════════════
# ModelRegistry.register
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_register_persists_and_returns_entry() -> None:
    """ModelRegistry.register adds, commits, refreshes, and returns the entry."""
    session = _mock_session()
    session.refresh = AsyncMock()
    entry = _make_model()

    result = await ModelRegistry.register(session, entry)

    session.add.assert_called_once_with(entry)
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(entry)
    assert result is entry


# ═══════════════════════════════════════════════════════════════════
# ModelRegistry.get
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_returns_entry_when_found() -> None:
    """ModelRegistry.get returns the entry when it exists."""
    session = _mock_session()
    entry = _make_model()
    session.get = AsyncMock(return_value=entry)

    result = await ModelRegistry.get(session, MODEL_ID)

    assert result is entry
    session.get.assert_awaited_once_with(ModelRegistryEntry, MODEL_ID)


@pytest.mark.asyncio
async def test_get_returns_none_when_not_found() -> None:
    """ModelRegistry.get returns None when entry does not exist."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    result = await ModelRegistry.get(session, uuid4())

    assert result is None


# ═══════════════════════════════════════════════════════════════════
# ModelRegistry.list
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_returns_paginated_entries() -> None:
    """ModelRegistry.list returns entries and total count."""
    session = _mock_session()
    entry = _make_model()

    count_result = MagicMock()
    count_result.all.return_value = [entry]
    page_result = MagicMock()
    page_result.all.return_value = [entry]
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    entries, total = await ModelRegistry.list(session, limit=10, offset=0)

    assert total == 1
    assert len(entries) == 1
    assert entries[0] is entry


@pytest.mark.asyncio
async def test_list_filters_by_provider() -> None:
    """ModelRegistry.list applies provider filter."""
    session = _mock_session()
    count_result = MagicMock()
    count_result.all.return_value = []
    page_result = MagicMock()
    page_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    entries, total = await ModelRegistry.list(
        session, provider="anthropic", limit=10, offset=0,
    )

    assert total == 0
    assert entries == []


@pytest.mark.asyncio
async def test_list_filters_by_is_active() -> None:
    """ModelRegistry.list applies is_active filter."""
    session = _mock_session()
    count_result = MagicMock()
    count_result.all.return_value = []
    page_result = MagicMock()
    page_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    entries, total = await ModelRegistry.list(
        session, is_active=False, limit=10, offset=0,
    )

    assert total == 0
    assert entries == []


@pytest.mark.asyncio
async def test_list_filters_by_capability() -> None:
    """ModelRegistry.list filters entries by capability in-memory."""
    session = _mock_session()
    entry_with = _make_model(capabilities=["chat", "vision"])
    entry_without = _make_model(model_id=MODEL_ID_2, capabilities=["chat"])

    count_result = MagicMock()
    count_result.all.return_value = [entry_with, entry_without]
    page_result = MagicMock()
    page_result.all.return_value = [entry_with, entry_without]
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    entries, total = await ModelRegistry.list(
        session, capability="vision", limit=10, offset=0,
    )

    # Total reflects the in-memory filter on the count query
    assert total == 1
    assert len(entries) == 1
    assert entries[0] is entry_with


@pytest.mark.asyncio
async def test_list_empty_capabilities_treated_as_empty() -> None:
    """Entry with empty capabilities is excluded when filtering by capability."""
    session = _mock_session()
    entry = _make_model(capabilities=[])

    count_result = MagicMock()
    count_result.all.return_value = [entry]
    page_result = MagicMock()
    page_result.all.return_value = [entry]
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    entries, total = await ModelRegistry.list(
        session, capability="chat", limit=10, offset=0,
    )

    assert total == 0
    assert entries == []


# ═══════════════════════════════════════════════════════════════════
# ModelRegistry.update
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_update_applies_changes_and_returns_entry() -> None:
    """ModelRegistry.update applies partial data and returns updated entry."""
    session = _mock_session()
    entry = _make_model(name="old-name")
    session.get = AsyncMock(return_value=entry)
    session.refresh = AsyncMock()

    result = await ModelRegistry.update(session, MODEL_ID, {"name": "new-name"})

    assert result is not None
    assert result.name == "new-name"
    session.add.assert_called_once_with(entry)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_returns_none_when_not_found() -> None:
    """ModelRegistry.update returns None when entry does not exist."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    result = await ModelRegistry.update(session, uuid4(), {"name": "x"})

    assert result is None
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_ignores_unknown_fields() -> None:
    """ModelRegistry.update skips keys that don't exist on the model."""
    session = _mock_session()
    entry = _make_model()
    session.get = AsyncMock(return_value=entry)
    session.refresh = AsyncMock()

    result = await ModelRegistry.update(
        session, MODEL_ID, {"nonexistent_field": "val"},
    )

    assert result is not None
    assert result.name == "gpt-4o"  # unchanged


# ═══════════════════════════════════════════════════════════════════
# ModelRegistry.delete
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_delete_returns_true_when_found() -> None:
    """ModelRegistry.delete removes the entry and returns True."""
    session = _mock_session()
    entry = _make_model()
    session.get = AsyncMock(return_value=entry)

    result = await ModelRegistry.delete(session, MODEL_ID)

    assert result is True
    session.delete.assert_awaited_once_with(entry)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_returns_false_when_not_found() -> None:
    """ModelRegistry.delete returns False when entry does not exist."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    result = await ModelRegistry.delete(session, uuid4())

    assert result is False
    session.delete.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════
# ModelRegistry.update_health
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_update_health_sets_status() -> None:
    """ModelRegistry.update_health updates health_status field."""
    session = _mock_session()
    entry = _make_model(health_status="healthy")
    session.get = AsyncMock(return_value=entry)
    session.refresh = AsyncMock()

    result = await ModelRegistry.update_health(
        session, MODEL_ID, health_status="degraded",
    )

    assert result is not None
    assert result.health_status == "degraded"


@pytest.mark.asyncio
async def test_update_health_sets_error_rate_and_latency() -> None:
    """ModelRegistry.update_health can also set error_rate and avg_latency_ms."""
    session = _mock_session()
    entry = _make_model()
    session.get = AsyncMock(return_value=entry)
    session.refresh = AsyncMock()

    result = await ModelRegistry.update_health(
        session,
        MODEL_ID,
        health_status="degraded",
        error_rate=0.15,
        avg_latency_ms=2000.0,
    )

    assert result is not None
    assert result.error_rate == 0.15
    assert result.avg_latency_ms == 2000.0


@pytest.mark.asyncio
async def test_update_health_returns_none_when_not_found() -> None:
    """ModelRegistry.update_health returns None for missing entry."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    result = await ModelRegistry.update_health(
        session, uuid4(), health_status="unhealthy",
    )

    assert result is None


# ═══════════════════════════════════════════════════════════════════
# RoutingRuleService — CRUD
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rule_create_persists_and_returns() -> None:
    """RoutingRuleService.create adds, commits, refreshes, and returns the rule."""
    session = _mock_session()
    session.refresh = AsyncMock()
    rule = _make_rule()

    result = await RoutingRuleService.create(session, rule)

    session.add.assert_called_once_with(rule)
    session.commit.assert_awaited_once()
    assert result is rule


@pytest.mark.asyncio
async def test_rule_get_found() -> None:
    """RoutingRuleService.get returns the rule when found."""
    session = _mock_session()
    rule = _make_rule()
    session.get = AsyncMock(return_value=rule)

    result = await RoutingRuleService.get(session, RULE_ID)

    assert result is rule


@pytest.mark.asyncio
async def test_rule_get_not_found() -> None:
    """RoutingRuleService.get returns None when not found."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    result = await RoutingRuleService.get(session, uuid4())

    assert result is None


@pytest.mark.asyncio
async def test_rule_list_returns_paginated_results() -> None:
    """RoutingRuleService.list returns rules and total count."""
    session = _mock_session()
    rule = _make_rule()

    count_result = MagicMock()
    count_result.all.return_value = [rule]
    page_result = MagicMock()
    page_result.all.return_value = [rule]
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    rules, total = await RoutingRuleService.list(session, limit=10, offset=0)

    assert total == 1
    assert len(rules) == 1


@pytest.mark.asyncio
async def test_rule_list_filters_by_is_active() -> None:
    """RoutingRuleService.list applies is_active filter."""
    session = _mock_session()
    count_result = MagicMock()
    count_result.all.return_value = []
    page_result = MagicMock()
    page_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    rules, total = await RoutingRuleService.list(
        session, is_active=True, limit=10, offset=0,
    )

    assert total == 0
    assert rules == []


@pytest.mark.asyncio
async def test_rule_list_filters_by_strategy() -> None:
    """RoutingRuleService.list applies strategy filter."""
    session = _mock_session()
    count_result = MagicMock()
    count_result.all.return_value = []
    page_result = MagicMock()
    page_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    rules, total = await RoutingRuleService.list(
        session, strategy="cost_optimized", limit=5, offset=0,
    )

    assert total == 0


@pytest.mark.asyncio
async def test_rule_update_found() -> None:
    """RoutingRuleService.update applies data and returns updated rule."""
    session = _mock_session()
    rule = _make_rule(name="old")
    session.get = AsyncMock(return_value=rule)
    session.refresh = AsyncMock()

    result = await RoutingRuleService.update(session, RULE_ID, {"name": "new"})

    assert result is not None
    assert result.name == "new"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_rule_update_not_found() -> None:
    """RoutingRuleService.update returns None when not found."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    result = await RoutingRuleService.update(session, uuid4(), {"name": "x"})

    assert result is None


@pytest.mark.asyncio
async def test_rule_delete_found() -> None:
    """RoutingRuleService.delete returns True when rule is deleted."""
    session = _mock_session()
    rule = _make_rule()
    session.get = AsyncMock(return_value=rule)

    result = await RoutingRuleService.delete(session, RULE_ID)

    assert result is True
    session.delete.assert_awaited_once_with(rule)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_rule_delete_not_found() -> None:
    """RoutingRuleService.delete returns False when not found."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    result = await RoutingRuleService.delete(session, uuid4())

    assert result is False
