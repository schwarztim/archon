"""Tests for the Improvement Engine endpoints and service logic.

Uses an in-memory SQLite database — no external services required.
LLM calls are mocked to avoid Azure OpenAI dependency.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker

# Ensure backend is importable
backend_dir = str(Path(__file__).resolve().parent.parent / "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.database import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models.improvement import ImprovementGap, ImprovementProposal  # noqa: E402
from app.services.improvement_engine import ImprovementEngineService  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    factory = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_engine):
    factory = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def _imp_url(path: str = "") -> str:
    return f"/api/v1/improvements{path}"


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_gap(session: AsyncSession, **kwargs) -> ImprovementGap:
    defaults = {
        "category": "compliance",
        "source": "governance",
        "severity": "medium",
        "title": "Test Gap",
        "description": "A test gap",
        "tenant_id": "tenant-1",
    }
    defaults.update(kwargs)
    gap = ImprovementGap(**defaults)
    session.add(gap)
    await session.commit()
    await session.refresh(gap)
    return gap


async def _seed_proposal(
    session: AsyncSession, gap_id: str | None = None, **kwargs
) -> ImprovementProposal:
    defaults = {
        "title": "Test Proposal",
        "description": "Fix the gap",
        "status": "proposed",
        "confidence_score": 0.8,
        "tenant_id": "tenant-1",
        "gap_id": gap_id,
    }
    defaults.update(kwargs)
    proposal = ImprovementProposal(**defaults)
    session.add(proposal)
    await session.commit()
    await session.refresh(proposal)
    return proposal


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


class TestImprovementEngineService:
    """Direct service-layer tests."""

    @pytest.mark.asyncio
    async def test_list_gaps_empty(self, db_session):
        """list_gaps returns empty list when no gaps exist."""
        gaps, total = await ImprovementEngineService.list_gaps(db_session)
        assert gaps == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_gaps_with_records(self, db_session):
        """list_gaps returns correct items."""
        await _seed_gap(db_session, tenant_id="t-1")
        await _seed_gap(db_session, tenant_id="t-1")
        await _seed_gap(db_session, tenant_id="t-2")
        gaps, total = await ImprovementEngineService.list_gaps(
            db_session, tenant_id="t-1"
        )
        assert total == 2
        assert all(g.tenant_id == "t-1" for g in gaps)

    @pytest.mark.asyncio
    async def test_list_gaps_category_filter(self, db_session):
        """Category filter correctly limits results."""
        await _seed_gap(db_session, category="security")
        await _seed_gap(db_session, category="compliance")
        gaps, total = await ImprovementEngineService.list_gaps(
            db_session, category="security"
        )
        assert total == 1
        assert gaps[0].category == "security"

    @pytest.mark.asyncio
    async def test_list_proposals_empty(self, db_session):
        """list_proposals returns empty when no proposals exist."""
        proposals, total = await ImprovementEngineService.list_proposals(db_session)
        assert proposals == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_update_proposal_status_approved(self, db_session):
        """Approving a proposal sets status, approved_by, and approved_at."""
        proposal = await _seed_proposal(db_session)
        updated = await ImprovementEngineService.update_proposal_status(
            db_session, proposal.id, status="approved", approved_by="user-admin"
        )
        assert updated is not None
        assert updated.status == "approved"
        assert updated.approved_by == "user-admin"
        assert updated.approved_at is not None

    @pytest.mark.asyncio
    async def test_update_proposal_invalid_status_raises(self, db_session):
        """Invalid status raises ValueError."""
        proposal = await _seed_proposal(db_session)
        with pytest.raises(ValueError, match="Invalid status"):
            await ImprovementEngineService.update_proposal_status(
                db_session, proposal.id, status="nonsense"
            )

    @pytest.mark.asyncio
    async def test_update_proposal_not_found_returns_none(self, db_session):
        """Non-existent proposal returns None."""
        result = await ImprovementEngineService.update_proposal_status(
            db_session, "does-not-exist", status="rejected"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_completing_proposal_resolves_gap(self, db_session):
        """Completing a proposal marks the linked gap as resolved."""
        gap = await _seed_gap(db_session)
        proposal = await _seed_proposal(db_session, gap_id=gap.id)

        await ImprovementEngineService.update_proposal_status(
            db_session, proposal.id, status="completed"
        )

        updated_gap = await db_session.get(ImprovementGap, gap.id)
        assert updated_gap is not None
        assert updated_gap.resolved is True
        assert updated_gap.resolved_at is not None
        assert updated_gap.resolved_by_proposal_id == proposal.id

    @pytest.mark.asyncio
    async def test_analyze_gaps_returns_none_on_llm_failure(self):
        """analyze_gaps returns None when the LLM call fails."""
        with patch(
            "app.services.improvement_engine._call_azure_openai", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = None
            result = await ImprovementEngineService.analyze_gaps(
                [
                    {
                        "category": "compliance",
                        "severity": "high",
                        "title": "T",
                        "description": "D",
                    }
                ]
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_gaps_empty_input_returns_empty_list(self):
        """Empty gap list returns empty analysis without calling LLM."""
        result = await ImprovementEngineService.analyze_gaps([])
        assert result == []

    @pytest.mark.asyncio
    async def test_generate_proposals_from_llm_output(self, db_session):
        """generate_proposals persists gaps and proposals correctly."""
        gaps = [
            {
                "category": "security",
                "source": "redteam",
                "severity": "critical",
                "title": "XSS vulnerability",
                "description": "Reflected XSS in search field",
                "tenant_id": "tenant-test",
            }
        ]
        analysis = [
            {
                "gap_index": 0,
                "title": "Fix XSS via input sanitisation",
                "description": "Apply output encoding to search parameter",
                "proposed_changes": {"steps": ["Sanitise input", "Add CSP header"]},
                "impact_analysis": {"risk": "high", "effort": "low", "benefit": "high"},
                "confidence_score": 0.92,
            }
        ]
        proposals = await ImprovementEngineService.generate_proposals(
            db_session, gaps=gaps, analysis=analysis, tenant_id="tenant-test"
        )
        assert len(proposals) == 1
        assert proposals[0].title == "Fix XSS via input sanitisation"
        assert proposals[0].confidence_score == 0.92
        assert proposals[0].gap_id is not None

    @pytest.mark.asyncio
    async def test_run_analysis_cycle_no_gaps(self, db_session):
        """Cycle with no gaps returns no_gaps status without calling LLM."""
        with patch.object(
            ImprovementEngineService, "collect_gaps", new_callable=AsyncMock
        ) as mock_collect:
            mock_collect.return_value = []
            summary = await ImprovementEngineService.run_analysis_cycle(db_session)
        assert summary["status"] == "no_gaps"
        assert summary["gaps_found"] == 0

    @pytest.mark.asyncio
    async def test_run_analysis_cycle_llm_unavailable(self, db_session):
        """Cycle still persists gaps when LLM is unavailable."""
        fake_gaps = [
            {
                "category": "compliance",
                "source": "test",
                "severity": "low",
                "title": "Gap A",
                "description": "desc",
                "tenant_id": None,
            }
        ]
        with patch.object(
            ImprovementEngineService, "collect_gaps", new_callable=AsyncMock
        ) as mock_collect:
            mock_collect.return_value = fake_gaps
            with patch.object(
                ImprovementEngineService, "analyze_gaps", new_callable=AsyncMock
            ) as mock_analyze:
                mock_analyze.return_value = None  # LLM down
                summary = await ImprovementEngineService.run_analysis_cycle(db_session)

        assert summary["gaps_found"] == 1
        assert summary["proposals_created"] == 0
        assert summary["status"] == "completed"


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


class TestImprovementEndpoints:
    """Integration tests against the FastAPI HTTP layer."""

    @pytest.mark.asyncio
    async def test_list_gaps_empty(self, client):
        resp = await client.get(_imp_url("/gaps"))
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    @pytest.mark.asyncio
    async def test_list_proposals_empty(self, client):
        resp = await client.get(_imp_url("/proposals"))
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    @pytest.mark.asyncio
    async def test_get_gap_not_found(self, client):
        resp = await client.get(_imp_url("/gaps/no-such-id"))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_proposal_not_found(self, client):
        resp = await client.get(_imp_url("/proposals/no-such-id"))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_proposal_not_found(self, client):
        resp = await client.put(
            _imp_url("/proposals/no-such-id"),
            json={"status": "approved"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_proposal_invalid_status(self, client, db_session):
        proposal = await _seed_proposal(db_session)
        resp = await client.put(
            _imp_url(f"/proposals/{proposal.id}"),
            json={"status": "bad-status"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_update_proposal_approve(self, client, db_session):
        proposal = await _seed_proposal(db_session)
        resp = await client.put(
            _imp_url(f"/proposals/{proposal.id}"),
            json={"status": "approved", "approved_by": "admin-user"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "approved"
        assert data["approved_by"] == "admin-user"

    @pytest.mark.asyncio
    async def test_dashboard_empty(self, client):
        resp = await client.get(_imp_url("/dashboard"))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["gaps"]["total"] == 0
        assert data["proposals"]["total"] == 0

    @pytest.mark.asyncio
    async def test_dashboard_with_data(self, client, db_session):
        """Dashboard reflects seeded data correctly."""
        await _seed_gap(db_session, category="security", severity="high")
        await _seed_gap(db_session, category="compliance", severity="low")
        await _seed_proposal(db_session, status="proposed")
        await _seed_proposal(db_session, status="approved")

        resp = await client.get(_imp_url("/dashboard"))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["gaps"]["total"] == 2
        assert data["proposals"]["total"] == 2
        assert data["proposals"]["by_status"].get("proposed") == 1
        assert data["proposals"]["by_status"].get("approved") == 1

    @pytest.mark.asyncio
    async def test_analyze_when_disabled(self, client):
        """Trigger analysis returns 503 when engine is disabled."""
        with patch("app.config.settings.IMPROVEMENT_ENGINE_ENABLED", False):
            resp = await client.post(_imp_url("/analyze"), json={})
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_analyze_trigger(self, client):
        """Triggering analysis returns a summary dict."""
        with patch.object(
            ImprovementEngineService, "run_analysis_cycle", new_callable=AsyncMock
        ) as mock_cycle:
            mock_cycle.return_value = {
                "gaps_found": 0,
                "proposals_created": 0,
                "status": "no_gaps",
            }
            with patch("app.config.settings.IMPROVEMENT_ENGINE_ENABLED", True):
                resp = await client.post(_imp_url("/analyze"), json={})
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert "gaps_found" in data
        assert "proposals_created" in data

    @pytest.mark.asyncio
    async def test_get_gap_by_id(self, client, db_session):
        """Fetching an existing gap returns full detail."""
        gap = await _seed_gap(db_session, title="Security gap")
        resp = await client.get(_imp_url(f"/gaps/{gap.id}"))
        assert resp.status_code == 200
        assert resp.json()["data"]["title"] == "Security gap"

    @pytest.mark.asyncio
    async def test_get_proposal_by_id(self, client, db_session):
        """Fetching an existing proposal returns full detail."""
        proposal = await _seed_proposal(db_session, title="My Proposal")
        resp = await client.get(_imp_url(f"/proposals/{proposal.id}"))
        assert resp.status_code == 200
        assert resp.json()["data"]["title"] == "My Proposal"

    @pytest.mark.asyncio
    async def test_list_gaps_with_filter(self, client, db_session):
        """Severity filter returns matching gaps only."""
        await _seed_gap(db_session, severity="critical", tenant_id=None)
        await _seed_gap(db_session, severity="low", tenant_id=None)
        resp = await client.get(_imp_url("/gaps?severity=critical"))
        assert resp.status_code == 200
        for g in resp.json()["data"]:
            assert g["severity"] == "critical"
