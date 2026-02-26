"""Fixtures for Azure OpenAI wiring tests."""
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import sys

backend_dir = str(Path(__file__).resolve().parent.parent.parent / "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.models.router import ModelRegistryEntry, ModelProvider, RoutingRule

SEED_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "azure_models_seed.json"


@pytest.fixture
def seed_data():
    """Load Azure models seed data."""
    with open(SEED_FILE) as f:
        return json.load(f)


@pytest.fixture
def azure_provider_data(seed_data):
    """Azure provider registration data."""
    return seed_data["provider"]


@pytest.fixture
def azure_models_data(seed_data):
    """All 26 Azure model definitions."""
    return seed_data["models"]


@pytest.fixture
def azure_routing_rules(seed_data):
    """All 5 routing rules."""
    return seed_data["routing_rules"]


@pytest.fixture
def all_model_names(azure_models_data):
    """Set of all registered model names."""
    return {m["name"] for m in azure_models_data}


@pytest.fixture
def models_by_capability(azure_models_data):
    """Group models by their capabilities."""
    groups: dict[str, list[dict]] = {}
    for m in azure_models_data:
        for cap in m["capabilities"]:
            groups.setdefault(cap, []).append(m)
    return groups


def _categorize(model: dict) -> str:
    """Categorize a model based on capabilities and naming conventions."""
    caps = set(model["capabilities"])
    name = model["name"]
    if "code" in caps:
        return "codex"
    if "reasoning" in caps:
        return "reasoning"
    if "embedding" in caps:
        return "embedding"
    if "realtime" in caps or "transcription" in caps:
        return "specialty"
    if "experimental" in name:
        return "legacy"
    return "chat"


@pytest.fixture
def models_by_category(azure_models_data):
    """Group models into chat/codex/reasoning/embedding/specialty/legacy."""
    groups: dict[str, list[dict]] = {}
    for m in azure_models_data:
        cat = _categorize(m)
        groups.setdefault(cat, []).append(m)
    return groups


@pytest.fixture
def mock_session():
    """Mock async database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    session.begin = MagicMock(return_value=AsyncMock())
    return session
