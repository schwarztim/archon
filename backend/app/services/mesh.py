"""Federated Agent Mesh gateway service for cross-organization communication."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.mesh import FederationConfig, MeshMessage, MeshNode, TrustRelationship


def _utcnow() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class MeshGateway:
    """Gateway for federated agent mesh operations.

    Handles node registration, trust establishment, cross-org messaging,
    and data isolation enforcement across organizational boundaries.
    """

    # ── Node registration ───────────────────────────────────────────

    @staticmethod
    async def register_node(
        session: AsyncSession,
        *,
        name: str,
        organization: str,
        endpoint_url: str,
        public_key: str,
        capabilities: list[str] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> MeshNode:
        """Register a new organization node in the mesh."""
        node = MeshNode(
            name=name,
            organization=organization,
            endpoint_url=endpoint_url,
            public_key=public_key,
            capabilities=capabilities or [],
            extra_metadata=extra_metadata or {},
            status="active",
            last_seen_at=_utcnow(),
        )
        session.add(node)
        await session.commit()
        await session.refresh(node)
        return node

    @staticmethod
    async def get_node(
        session: AsyncSession,
        node_id: UUID,
    ) -> MeshNode | None:
        """Return a mesh node by ID."""
        return await session.get(MeshNode, node_id)

    @staticmethod
    async def list_peers(
        session: AsyncSession,
        *,
        status: str | None = None,
        organization: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[MeshNode], int]:
        """Return paginated mesh nodes with optional filters."""
        base = select(MeshNode)
        if status is not None:
            base = base.where(MeshNode.status == status)
        if organization is not None:
            base = base.where(MeshNode.organization == organization)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(
            MeshNode.created_at.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        nodes = list(result.all())
        return nodes, total

    # ── Trust establishment ─────────────────────────────────────────

    @staticmethod
    async def establish_trust(
        session: AsyncSession,
        *,
        requesting_node_id: UUID,
        target_node_id: UUID,
        trust_level: str = "standard",
        allowed_data_categories: list[str] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> TrustRelationship:
        """Create a trust relationship between two mesh nodes."""
        requesting = await session.get(MeshNode, requesting_node_id)
        if requesting is None:
            raise ValueError(f"Requesting node {requesting_node_id} not found")
        target = await session.get(MeshNode, target_node_id)
        if target is None:
            raise ValueError(f"Target node {target_node_id} not found")

        trust = TrustRelationship(
            requesting_node_id=requesting_node_id,
            target_node_id=target_node_id,
            trust_level=trust_level,
            allowed_data_categories=allowed_data_categories or [],
            extra_metadata=extra_metadata or {},
            status="active",
            established_at=_utcnow(),
        )
        session.add(trust)
        await session.commit()
        await session.refresh(trust)
        return trust

    @staticmethod
    async def revoke_trust(
        session: AsyncSession,
        trust_id: UUID,
    ) -> TrustRelationship | None:
        """Revoke (kill-switch) a trust relationship immediately."""
        trust = await session.get(TrustRelationship, trust_id)
        if trust is None:
            return None
        trust.status = "revoked"
        trust.revoked_at = _utcnow()
        trust.updated_at = _utcnow()
        session.add(trust)
        await session.commit()
        await session.refresh(trust)
        return trust

    @staticmethod
    async def get_trust(
        session: AsyncSession,
        trust_id: UUID,
    ) -> TrustRelationship | None:
        """Return a trust relationship by ID."""
        return await session.get(TrustRelationship, trust_id)

    @staticmethod
    async def list_trust_relationships(
        session: AsyncSession,
        *,
        node_id: UUID | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[TrustRelationship], int]:
        """Return paginated trust relationships with optional filters."""
        base = select(TrustRelationship)
        if node_id is not None:
            base = base.where(
                (TrustRelationship.requesting_node_id == node_id)
                | (TrustRelationship.target_node_id == node_id)
            )
        if status is not None:
            base = base.where(TrustRelationship.status == status)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(
            TrustRelationship.created_at.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        relationships = list(result.all())
        return relationships, total

    # ── Cross-org messaging ─────────────────────────────────────────

    @staticmethod
    async def send_message(
        session: AsyncSession,
        *,
        source_node_id: UUID,
        target_node_id: UUID,
        content: str,
        message_type: str = "request",
        data_category: str | None = None,
        correlation_id: UUID | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> MeshMessage:
        """Send a message between mesh nodes with data isolation enforcement.

        Validates that an active trust relationship exists and that the
        data category is allowed before permitting the message.
        """
        # Verify active trust exists between source and target
        stmt = select(TrustRelationship).where(
            TrustRelationship.status == "active",
            (
                (TrustRelationship.requesting_node_id == source_node_id)
                & (TrustRelationship.target_node_id == target_node_id)
            )
            | (
                (TrustRelationship.requesting_node_id == target_node_id)
                & (TrustRelationship.target_node_id == source_node_id)
            ),
        )
        result = await session.exec(stmt)
        trust = result.first()
        if trust is None:
            raise ValueError(
                "No active trust relationship between source and target nodes"
            )

        # Data isolation: check category is allowed
        if data_category and trust.allowed_data_categories:
            if data_category not in trust.allowed_data_categories:
                raise ValueError(
                    f"Data category '{data_category}' not allowed by trust policy"
                )

        message = MeshMessage(
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            content=content,
            message_type=message_type,
            data_category=data_category,
            correlation_id=correlation_id,
            extra_metadata=extra_metadata or {},
            status="delivered",
            delivered_at=_utcnow(),
        )
        session.add(message)
        await session.commit()
        await session.refresh(message)
        return message

    @staticmethod
    async def get_message(
        session: AsyncSession,
        message_id: UUID,
    ) -> MeshMessage | None:
        """Return a mesh message by ID."""
        return await session.get(MeshMessage, message_id)

    @staticmethod
    async def list_messages(
        session: AsyncSession,
        *,
        node_id: UUID | None = None,
        status: str | None = None,
        data_category: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[MeshMessage], int]:
        """Return paginated mesh messages with optional filters."""
        base = select(MeshMessage)
        if node_id is not None:
            base = base.where(
                (MeshMessage.source_node_id == node_id)
                | (MeshMessage.target_node_id == node_id)
            )
        if status is not None:
            base = base.where(MeshMessage.status == status)
        if data_category is not None:
            base = base.where(MeshMessage.data_category == data_category)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(
            MeshMessage.created_at.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        messages = list(result.all())
        return messages, total


__all__ = [
    "MeshGateway",
]
