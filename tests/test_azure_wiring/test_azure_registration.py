import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from sqlmodel import select

from backend.app.models.router import ModelRegistryEntry, RoutingRule
from backend.app.services.router_service import ModelRouterService
from backend.app.interfaces.models.enterprise import AuthenticatedUser

# Mock data
MOCK_TENANT_ID = "default"
MOCK_USER = AuthenticatedUser(
    id=str(uuid4()),
    email="test@example.com",
    permissions=["router:read", "router:create", "router:update", "router:execute"],
    tenant_id=MOCK_TENANT_ID,
    roles=["admin"],
)


@pytest.mark.asyncio
async def test_register_azure_provider(session):
    """Test registering the Azure OpenAI provider."""
    # Since the provider registration logic is implicit (no separate provider table),
    # we test that we can register a model which acts as a provider entry.

    # Check if any model exists first
    stmt = select(ModelRegistryEntry).where(
        ModelRegistryEntry.provider == "azure_openai"
    )
    result = await session.exec(stmt)
    existing_count = len(result.all())

    # We expect the seed script to have run or be runnable.
    # For this test, we'll verify the seed data structure against the schema.

    provider_name = "azure-qrg-sandbox"

    # Simulate registration
    entry = ModelRegistryEntry(
        id=uuid4(),
        name=provider_name,
        provider="azure_openai",
        model_id="model-router,gpt-4",  # Represents multiple models
        capabilities=["chat", "embedding"],
        cost_per_input_token=0.01,
        cost_per_output_token=0.03,
        avg_latency_ms=200.0,
        data_classification="internal",
        is_active=True,
        config={"tenant_id": MOCK_TENANT_ID, "geo_residency": "us"},
    )
    session.add(entry)
    await session.commit()

    # Verify it was added
    stmt = select(ModelRegistryEntry).where(ModelRegistryEntry.name == provider_name)
    result = await session.exec(stmt)
    stored = result.first()

    assert stored is not None
    assert stored.provider == "azure_openai"
    assert stored.data_classification == "internal"


@pytest.mark.asyncio
async def test_register_all_26_models(session):
    """Test that we can register all 26 required Azure models."""
    model_names = [
        "model-router",
        "modelrouter",
        "gpt-5.2",
        "gpt-5.2-chat",
        "gpt-5-mini",
        "gpt-5-chat",
        "qrg-gpt-4.1",
        "qrg-gpt-4.1-mini",
        "gpt-4",
        "gpt-4o-mini",
        "gpt-5.2-codex",
        "gpt-5.1-codex-max",
        "gpt-5.1-codex-mini",
        "o1-experiment",
        "qrg-o3-mini",
        "o1-mini",
        "text-embedding-3-small-sandbox",
        "text-embeddings-3-large-sandbox",
        "qrg-embedding-experimental",
        "gpt-realtime",
        "gpt-4o-mini-realtime-preview",
        "whisper-sandbox",
        "qrg-gpt35turbo16k-experimental",
        "qrg-gpt35turbo4k-experimental",
        "qrq-gpt4turbo-experimental",
        "qrg-gpt4o-experimental",
    ]

    for name in model_names:
        entry = ModelRegistryEntry(
            id=uuid4(),
            name=name,
            provider="azure_openai",
            model_id=name,  # Simply using name as ID for this test
            capabilities=["chat"],
            cost_per_input_token=0.001,
            cost_per_output_token=0.002,
            is_active=True,
            config={"tenant_id": MOCK_TENANT_ID},
        )
        session.add(entry)

    await session.commit()

    # Verify count
    stmt = select(ModelRegistryEntry).where(
        ModelRegistryEntry.provider == "azure_openai"
    )
    result = await session.exec(stmt)
    models = result.all()

    # Filter to just the ones we added (in case previous test added some)
    added_models = [m for m in models if m.name in model_names]
    assert len(added_models) == 26


@pytest.mark.asyncio
async def test_routing_rules_config(session):
    """Test configuration of the 5 required routing rules."""
    rule_names = [
        "cost-optimized-default",
        "code-generation",
        "reasoning-tasks",
        "embedding-pipeline",
        "high-volume",
    ]

    for name in rule_names:
        rule = RoutingRule(
            id=uuid4(),
            name=name,
            strategy="balanced",
            priority=10,
            conditions={"tenant_id": MOCK_TENANT_ID},
            is_active=True,
        )
        session.add(rule)

    await session.commit()

    for name in rule_names:
        stmt = select(RoutingRule).where(RoutingRule.name == name)
        result = await session.exec(stmt)
        assert result.first() is not None


@pytest.mark.asyncio
async def test_fallback_chain_logic(session):
    """Test that fallback chains are correctly stored and retrieved."""
    # Create a rule with a fallback chain
    fallback_models = ["gpt-4o-mini", "gpt-3.5-turbo"]
    rule = RoutingRule(
        id=uuid4(),
        name="test-fallback-rule",
        strategy="custom",
        fallback_chain=fallback_models,
        conditions={"tenant_id": MOCK_TENANT_ID},
    )
    session.add(rule)
    await session.commit()

    # Retrieve and verify
    stmt = select(RoutingRule).where(RoutingRule.name == "test-fallback-rule")
    result = await session.exec(stmt)
    stored_rule = result.first()

    assert stored_rule.fallback_chain == fallback_models


@pytest.mark.asyncio
async def test_cost_tracking_fields(session):
    """Test that cost tracking fields are present and queryable."""
    model_name = "expensive-model"
    cost_input = 0.05
    cost_output = 0.15

    entry = ModelRegistryEntry(
        id=uuid4(),
        name=model_name,
        provider="azure_openai",
        model_id="expensive-1",
        cost_per_input_token=cost_input,
        cost_per_output_token=cost_output,
        config={"tenant_id": MOCK_TENANT_ID},
    )
    session.add(entry)
    await session.commit()

    stmt = select(ModelRegistryEntry).where(ModelRegistryEntry.name == model_name)
    result = await session.exec(stmt)
    stored = result.first()

    assert stored.cost_per_input_token == cost_input
    assert stored.cost_per_output_token == cost_output
