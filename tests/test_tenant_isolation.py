"""Tenant isolation verification tests for Agent and AuditLog models.

Ensures that tenant_id filtering correctly isolates records across tenants.
Uses an in-memory SQLite database — no external services required.
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

# Ensure backend is importable
backend_dir = str(Path(__file__).resolve().parent.parent / "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.models import Agent, AuditLog  # noqa: E402


@pytest.fixture(name="session")
def session_fixture():
    """Create an in-memory SQLite engine and yield a session."""
    engine = create_engine("sqlite://", echo=False)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# ---------------------------------------------------------------------------
# Agent tenant isolation
# ---------------------------------------------------------------------------


class TestAgentTenantIsolation:
    """Verify that Agent records are correctly filtered by tenant_id."""

    def test_agents_filtered_by_tenant(self, session: Session):
        owner = uuid4()
        agents = [
            Agent(name="Agent A", definition={}, owner_id=owner, tenant_id="tenant-1"),
            Agent(name="Agent B", definition={}, owner_id=owner, tenant_id="tenant-1"),
            Agent(name="Agent C", definition={}, owner_id=owner, tenant_id="tenant-2"),
            Agent(name="Agent D", definition={}, owner_id=owner, tenant_id=None),
        ]
        for a in agents:
            session.add(a)
        session.commit()

        t1 = session.exec(select(Agent).where(Agent.tenant_id == "tenant-1")).all()
        t2 = session.exec(select(Agent).where(Agent.tenant_id == "tenant-2")).all()

        assert len(t1) == 2
        assert all(a.tenant_id == "tenant-1" for a in t1)
        assert len(t2) == 1
        assert t2[0].name == "Agent C"

    def test_no_cross_tenant_leakage(self, session: Session):
        owner = uuid4()
        session.add(
            Agent(name="Secret", definition={}, owner_id=owner, tenant_id="tenant-x")
        )
        session.commit()

        results = session.exec(select(Agent).where(Agent.tenant_id == "tenant-y")).all()
        assert results == []


# ---------------------------------------------------------------------------
# AuditLog tenant isolation
# ---------------------------------------------------------------------------


class TestAuditLogTenantIsolation:
    """Verify that AuditLog records are correctly filtered by tenant_id."""

    def test_audit_logs_filtered_by_tenant(self, session: Session):
        actor = uuid4()
        resource = uuid4()
        logs = [
            AuditLog(
                actor_id=actor,
                tenant_id="t-aaa",
                action="create",
                resource_type="agent",
                resource_id=resource,
            ),
            AuditLog(
                actor_id=actor,
                tenant_id="t-aaa",
                action="update",
                resource_type="agent",
                resource_id=resource,
            ),
            AuditLog(
                actor_id=actor,
                tenant_id="t-bbb",
                action="delete",
                resource_type="agent",
                resource_id=resource,
            ),
        ]
        for log in logs:
            session.add(log)
        session.commit()

        aaa = session.exec(select(AuditLog).where(AuditLog.tenant_id == "t-aaa")).all()
        bbb = session.exec(select(AuditLog).where(AuditLog.tenant_id == "t-bbb")).all()

        assert len(aaa) == 2
        assert len(bbb) == 1
        assert bbb[0].action == "delete"

    def test_null_tenant_not_returned(self, session: Session):
        actor = uuid4()
        resource = uuid4()
        session.add(
            AuditLog(
                actor_id=actor,
                tenant_id=None,
                action="read",
                resource_type="agent",
                resource_id=resource,
            )
        )
        session.commit()

        results = session.exec(
            select(AuditLog).where(AuditLog.tenant_id == "any-tenant")
        ).all()
        assert results == []
