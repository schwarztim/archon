"""CRUD service for Model (LLM provider) records."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models import Model


class ModelService:
    """Encapsulates all Model persistence operations."""

    @staticmethod
    async def create(session: AsyncSession, model: Model) -> Model:
        """Persist a new model configuration and return it."""
        session.add(model)
        await session.commit()
        await session.refresh(model)
        return model

    @staticmethod
    async def get(session: AsyncSession, model_id: UUID) -> Model | None:
        """Return a single model by ID, or None if not found."""
        return await session.get(Model, model_id)

    @staticmethod
    async def list(
        session: AsyncSession,
        *,
        provider: str | None = None,
        is_active: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Model], int]:
        """Return paginated models with optional filters and total count."""
        base = select(Model)
        if provider is not None:
            base = base.where(Model.provider == provider)
        if is_active is not None:
            base = base.where(Model.is_active == is_active)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(Model.created_at.desc())  # type: ignore[union-attr]
        result = await session.exec(stmt)
        models = list(result.all())
        return models, total

    @staticmethod
    async def update(
        session: AsyncSession,
        model_id: UUID,
        data: dict[str, Any],
    ) -> Model | None:
        """Apply partial updates to an existing model. Returns None if not found."""
        model = await session.get(Model, model_id)
        if model is None:
            return None
        for key, value in data.items():
            if hasattr(model, key):
                setattr(model, key, value)
        session.add(model)
        await session.commit()
        await session.refresh(model)
        return model

    @staticmethod
    async def delete(session: AsyncSession, model_id: UUID) -> bool:
        """Delete a model by ID. Returns True if deleted, False if not found."""
        model = await session.get(Model, model_id)
        if model is None:
            return False
        await session.delete(model)
        await session.commit()
        return True
