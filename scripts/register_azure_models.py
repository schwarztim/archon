"""Register Azure OpenAI deployments in the model registry.

Usage:
    PYTHONPATH=backend python -m scripts.register_azure_models
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from uuid import uuid4

from sqlmodel import select

sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))

from app.database import async_session_factory
from app.models.router import ModelRegistryEntry, RoutingRule

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AZURE_ENDPOINT = os.getenv(
    "AZURE_OPENAI_ENDPOINT",
    "https://YOUR_AZURE_ENDPOINT.cognitiveservices.azure.com",
)
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")


def _load_seed_entries() -> list[dict[str, object]]:
    seed_file = Path(__file__).resolve().parent.parent / "data/azure_models_seed.json"
    if not seed_file.exists():
        raise FileNotFoundError(f"Seed file not found: {seed_file}")
    with seed_file.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Azure seed data must be an object with a 'models' key.")
    models = data.get("models")
    if not isinstance(models, list):
        raise ValueError("Azure seed data must include a list of models.")
    return models


def _apply_defaults(entry: dict[str, object]) -> dict[str, object]:
    config = dict(entry.get("config", {}) or {})
    config.setdefault("endpoint", AZURE_ENDPOINT)
    config.setdefault("api_version", AZURE_API_VERSION)
    config.setdefault("deployment_name", entry.get("model_id"))
    entry["config"] = config
    entry.setdefault("provider", "azure_openai")
    return entry


async def register_azure_models() -> None:
    """Upsert Azure OpenAI deployments into the model registry."""
    models_data = _load_seed_entries()
    entries = [_apply_defaults(entry) for entry in models_data]

    async with async_session_factory() as session:
        for entry in entries:
            name = entry.get("name")
            if not isinstance(name, str):
                logger.warning("Skipping entry with invalid name: %s", entry)
                continue

            stmt = select(ModelRegistryEntry).where(ModelRegistryEntry.name == name)
            result = await session.exec(stmt)
            existing = result.first()

            if existing:
                logger.info("Updating existing model: %s", name)
                existing.provider = str(entry.get("provider", "azure_openai"))
                existing.model_id = str(entry.get("model_id", name))
                existing.capabilities = entry.get("capabilities", [])
                existing.context_window = int(entry.get("context_window", 4096))
                existing.supports_streaming = bool(
                    entry.get("supports_streaming", True)
                )
                existing.cost_per_input_token = float(
                    entry.get("cost_per_input_token", 0.0)
                )
                existing.cost_per_output_token = float(
                    entry.get("cost_per_output_token", 0.0)
                )
                existing.speed_tier = str(entry.get("speed_tier", "medium"))
                existing.avg_latency_ms = float(entry.get("avg_latency_ms", 500.0))
                existing.data_classification = str(
                    entry.get("data_classification", "general")
                )
                existing.is_on_prem = bool(entry.get("is_on_prem", False))
                existing.is_active = bool(entry.get("is_active", True))
                existing.health_status = str(entry.get("health_status", "healthy"))
                existing.config = entry.get("config", {})
                session.add(existing)
                continue

            logger.info("Registering new model: %s", name)
            new_entry = ModelRegistryEntry(
                id=uuid4(),
                name=name,
                provider=str(entry.get("provider", "azure_openai")),
                model_id=str(entry.get("model_id", name)),
                capabilities=entry.get("capabilities", []),
                context_window=int(entry.get("context_window", 4096)),
                supports_streaming=bool(entry.get("supports_streaming", True)),
                cost_per_input_token=float(entry.get("cost_per_input_token", 0.0)),
                cost_per_output_token=float(entry.get("cost_per_output_token", 0.0)),
                speed_tier=str(entry.get("speed_tier", "medium")),
                avg_latency_ms=float(entry.get("avg_latency_ms", 500.0)),
                data_classification=str(entry.get("data_classification", "general")),
                is_on_prem=bool(entry.get("is_on_prem", False)),
                is_active=bool(entry.get("is_active", True)),
                health_status=str(entry.get("health_status", "healthy")),
                config=entry.get("config", {}),
                vault_secret_path=entry.get("vault_secret_path"),
            )
            session.add(new_entry)

        await session.commit()
        logger.info("Azure model registry seed complete (%s entries).", len(entries))


async def register_routing_rules() -> None:
    """Register the 5 routing rules for optimal model selection."""

    # Define the 5 routing rules
    routing_rules = [
        {
            "name": "cost-optimized-default",
            "description": "Cost-optimized routing rule preferring budget-friendly models for general tasks",
            "strategy": "cost_optimized",
            "priority": 100,
            "weight_cost": 0.6,
            "weight_latency": 0.15,
            "weight_capability": 0.15,
            "weight_sensitivity": 0.1,
            "fallback_chain": ["gpt-4o-mini", "gpt-5-mini"],
        },
        {
            "name": "code-generation",
            "description": "Specialized routing for code generation tasks using advanced code models",
            "strategy": "performance_optimized",
            "priority": 200,
            "weight_cost": 0.1,
            "weight_latency": 0.2,
            "weight_capability": 0.6,
            "weight_sensitivity": 0.1,
            "conditions": {"task_type": "code"},
            "fallback_chain": ["gpt-5.2-codex", "gpt-5.1-codex-max"],
        },
        {
            "name": "reasoning-tasks",
            "description": "High-performance routing for complex reasoning and analysis tasks",
            "strategy": "performance_optimized",
            "priority": 250,
            "weight_cost": 0.1,
            "weight_latency": 0.1,
            "weight_capability": 0.7,
            "weight_sensitivity": 0.1,
            "conditions": {"task_type": "reasoning"},
            "fallback_chain": ["o1-experiment", "qrg-o3-mini"],
        },
        {
            "name": "embedding-pipeline",
            "description": "Optimized routing for embedding generation in data pipelines",
            "strategy": "balanced",
            "priority": 150,
            "weight_cost": 0.3,
            "weight_latency": 0.4,
            "weight_capability": 0.25,
            "weight_sensitivity": 0.05,
            "conditions": {"task_type": "embedding"},
            "fallback_chain": ["text-embedding-3-small-sandbox"],
        },
        {
            "name": "high-volume",
            "description": "Cost-effective routing for high volume requests with moderate cost weight",
            "strategy": "cost_optimized",
            "priority": 75,
            "weight_cost": 0.5,
            "weight_latency": 0.25,
            "weight_capability": 0.2,
            "weight_sensitivity": 0.05,
            "conditions": {"volume": "high"},
            "fallback_chain": ["gpt-5-mini", "gpt-4o-mini"],
        },
    ]

    async with async_session_factory() as session:
        for rule_data in routing_rules:
            name = rule_data["name"]

            # Check if rule already exists
            stmt = select(RoutingRule).where(RoutingRule.name == name)
            result = await session.exec(stmt)
            existing = result.first()

            if existing:
                logger.info("Updating existing routing rule: %s", name)
                existing.description = rule_data["description"]
                existing.strategy = rule_data["strategy"]
                existing.priority = rule_data["priority"]
                existing.weight_cost = rule_data["weight_cost"]
                existing.weight_latency = rule_data["weight_latency"]
                existing.weight_capability = rule_data["weight_capability"]
                existing.weight_sensitivity = rule_data["weight_sensitivity"]
                existing.conditions = rule_data.get("conditions", {})
                existing.fallback_chain = rule_data["fallback_chain"]
                session.add(existing)
                continue

            logger.info("Registering new routing rule: %s", name)
            new_rule = RoutingRule(
                id=uuid4(),
                name=name,
                description=rule_data["description"],
                strategy=rule_data["strategy"],
                priority=rule_data["priority"],
                is_active=True,
                weight_cost=rule_data["weight_cost"],
                weight_latency=rule_data["weight_latency"],
                weight_capability=rule_data["weight_capability"],
                weight_sensitivity=rule_data["weight_sensitivity"],
                conditions=rule_data.get("conditions", {}),
                fallback_chain=rule_data["fallback_chain"],
            )
            session.add(new_rule)

        await session.commit()
        logger.info(
            "Routing rules registration complete (%s rules).", len(routing_rules)
        )


async def main() -> None:
    """Register Azure models and routing rules."""
    await register_azure_models()
    await register_routing_rules()


if __name__ == "__main__":
    asyncio.run(main())
