"""SentinelScan engine for Archon — shadow AI discovery, risk classification, and posture management."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.sentinelscan import (
    DiscoveredService,
    DiscoveryScan,
    RiskClassification,
)


def _utcnow() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


# ── Risk scoring constants ──────────────────────────────────────────

_SENSITIVITY_SCORES: dict[str, int] = {
    "restricted": 40,
    "confidential": 30,
    "internal": 15,
    "public": 5,
    "unknown": 20,
}

_PROVIDER_CAPABILITY_SCORES: dict[str, int] = {
    "openai": 25,
    "anthropic": 25,
    "google": 20,
    "microsoft": 20,
    "cohere": 15,
    "custom": 10,
}

_RISK_TIER_THRESHOLDS: list[tuple[int, str]] = [
    (80, "critical"),
    (60, "high"),
    (40, "medium"),
    (20, "low"),
    (0, "informational"),
]


class SentinelScanner:
    """Discovers, classifies, and tracks shadow AI usage across an organization.

    All methods are async statics that accept an ``AsyncSession``,
    following the same pattern as ``GovernanceEngine``.
    """

    # ── Discovery Scan Management ───────────────────────────────────

    @staticmethod
    async def create_scan(
        session: AsyncSession,
        scan: DiscoveryScan,
    ) -> DiscoveryScan:
        """Create and persist a new discovery scan."""
        session.add(scan)
        await session.commit()
        await session.refresh(scan)
        return scan

    @staticmethod
    async def get_scan(
        session: AsyncSession,
        scan_id: UUID,
    ) -> DiscoveryScan | None:
        """Return a single discovery scan by ID."""
        return await session.get(DiscoveryScan, scan_id)

    @staticmethod
    async def list_scans(
        session: AsyncSession,
        *,
        scan_type: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[DiscoveryScan], int]:
        """Return paginated discovery scans with optional filters and total count."""
        base = select(DiscoveryScan)
        if scan_type is not None:
            base = base.where(DiscoveryScan.scan_type == scan_type)
        if status is not None:
            base = base.where(DiscoveryScan.status == status)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(
            DiscoveryScan.created_at.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    @staticmethod
    async def run_scan(
        session: AsyncSession,
        scan_id: UUID,
    ) -> DiscoveryScan | None:
        """Mark a scan as running and simulate discovery.

        In production this would dispatch to pluggable discovery modules.
        Here it transitions the scan status and records timestamps.
        """
        scan = await session.get(DiscoveryScan, scan_id)
        if scan is None:
            return None

        scan.status = "running"
        scan.started_at = _utcnow()
        scan.updated_at = _utcnow()
        session.add(scan)
        await session.commit()
        await session.refresh(scan)
        return scan

    @staticmethod
    async def complete_scan(
        session: AsyncSession,
        scan_id: UUID,
        *,
        results_summary: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> DiscoveryScan | None:
        """Mark a scan as completed (or failed) and store results."""
        scan = await session.get(DiscoveryScan, scan_id)
        if scan is None:
            return None

        now = _utcnow()
        if error_message:
            scan.status = "failed"
            scan.error_message = error_message
        else:
            scan.status = "completed"

        if results_summary is not None:
            scan.results_summary = results_summary

        # Count discovered services for this scan
        svc_stmt = select(DiscoveredService).where(
            DiscoveredService.scan_id == scan_id
        )
        svc_result = await session.exec(svc_stmt)
        scan.services_found = len(svc_result.all())

        scan.completed_at = now
        scan.updated_at = now
        session.add(scan)
        await session.commit()
        await session.refresh(scan)
        return scan

    # ── Discovered Service Tracking ─────────────────────────────────

    @staticmethod
    async def add_discovered_service(
        session: AsyncSession,
        service: DiscoveredService,
    ) -> DiscoveredService:
        """Record a newly discovered AI service."""
        session.add(service)
        await session.commit()
        await session.refresh(service)
        return service

    @staticmethod
    async def get_discovered_service(
        session: AsyncSession,
        service_id: UUID,
    ) -> DiscoveredService | None:
        """Return a single discovered service by ID."""
        return await session.get(DiscoveredService, service_id)

    @staticmethod
    async def list_discovered_services(
        session: AsyncSession,
        *,
        scan_id: UUID | None = None,
        service_type: str | None = None,
        provider: str | None = None,
        department: str | None = None,
        is_sanctioned: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[DiscoveredService], int]:
        """Return paginated discovered services with optional filters and total count."""
        base = select(DiscoveredService)
        if scan_id is not None:
            base = base.where(DiscoveredService.scan_id == scan_id)
        if service_type is not None:
            base = base.where(DiscoveredService.service_type == service_type)
        if provider is not None:
            base = base.where(DiscoveredService.provider == provider)
        if department is not None:
            base = base.where(DiscoveredService.department == department)
        if is_sanctioned is not None:
            base = base.where(DiscoveredService.is_sanctioned == is_sanctioned)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(
            DiscoveredService.created_at.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    @staticmethod
    async def update_discovered_service(
        session: AsyncSession,
        service_id: UUID,
        data: dict[str, Any],
    ) -> DiscoveredService | None:
        """Partial-update a discovered service. Returns None if not found."""
        service = await session.get(DiscoveredService, service_id)
        if service is None:
            return None
        for key, value in data.items():
            if hasattr(service, key):
                setattr(service, key, value)
        service.updated_at = _utcnow()
        session.add(service)
        await session.commit()
        await session.refresh(service)
        return service

    # ── Risk Classification ─────────────────────────────────────────

    @staticmethod
    async def classify_risk(
        session: AsyncSession,
        service_id: UUID,
    ) -> RiskClassification | None:
        """Compute and persist a risk classification for a discovered service.

        Scoring factors:
        - Data sensitivity (0–40)
        - Blast radius based on user count (0–20)
        - Compliance gap (sanctioned vs unsanctioned) (0–15)
        - Model capability based on provider (0–25)
        """
        service = await session.get(DiscoveredService, service_id)
        if service is None:
            return None

        data_score = _SENSITIVITY_SCORES.get(service.data_sensitivity, 20)
        blast_score = min(20, service.user_count)  # cap at 20
        compliance_score = 0 if service.is_sanctioned else 15
        capability_score = _PROVIDER_CAPABILITY_SCORES.get(service.provider, 10)

        total_score = data_score + blast_score + compliance_score + capability_score
        total_score = min(100, max(0, total_score))

        tier = "informational"
        for threshold, tier_name in _RISK_TIER_THRESHOLDS:
            if total_score >= threshold:
                tier = tier_name
                break

        # Build violation list
        violations: list[str] = []
        if not service.is_sanctioned:
            violations.append("Unsanctioned AI service detected")
        if service.data_sensitivity in ("restricted", "confidential"):
            violations.append(f"Service accesses {service.data_sensitivity} data")
        if service.user_count > 50:
            violations.append(f"High blast radius: {service.user_count} users")

        # Build recommended actions
        actions: list[str] = []
        if not service.is_sanctioned:
            actions.append("Review and approve or block this service")
        if service.data_sensitivity in ("restricted", "confidential"):
            actions.append("Conduct data flow audit")
        if total_score >= 60:
            actions.append("Escalate to security team for immediate review")
        if service.owner is None:
            actions.append("Assign a responsible owner")

        factors = {
            "data_sensitivity": data_score,
            "blast_radius": blast_score,
            "compliance_gap": compliance_score,
            "model_capability": capability_score,
        }

        # Upsert: check if classification already exists
        existing_stmt = select(RiskClassification).where(
            RiskClassification.service_id == service_id
        )
        existing_result = await session.exec(existing_stmt)
        existing = existing_result.first()

        now = _utcnow()
        if existing:
            existing.risk_tier = tier
            existing.risk_score = total_score
            existing.factors = factors
            existing.data_sensitivity_score = data_score
            existing.blast_radius_score = blast_score
            existing.compliance_score = compliance_score
            existing.model_capability_score = capability_score
            existing.policy_violations = violations
            existing.recommended_actions = actions
            existing.updated_at = now
            session.add(existing)
            await session.commit()
            await session.refresh(existing)
            return existing

        classification = RiskClassification(
            service_id=service_id,
            risk_tier=tier,
            risk_score=total_score,
            factors=factors,
            data_sensitivity_score=data_score,
            blast_radius_score=blast_score,
            compliance_score=compliance_score,
            model_capability_score=capability_score,
            policy_violations=violations,
            recommended_actions=actions,
            classified_at=now,
            updated_at=now,
        )
        session.add(classification)
        await session.commit()
        await session.refresh(classification)
        return classification

    @staticmethod
    async def get_risk_classification(
        session: AsyncSession,
        service_id: UUID,
    ) -> RiskClassification | None:
        """Return the risk classification for a given service."""
        stmt = select(RiskClassification).where(
            RiskClassification.service_id == service_id
        )
        result = await session.exec(stmt)
        return result.first()

    @staticmethod
    async def list_risk_classifications(
        session: AsyncSession,
        *,
        risk_tier: str | None = None,
        min_score: int | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[RiskClassification], int]:
        """Return paginated risk classifications with optional filters."""
        base = select(RiskClassification)
        if risk_tier is not None:
            base = base.where(RiskClassification.risk_tier == risk_tier)
        if min_score is not None:
            base = base.where(RiskClassification.risk_score >= min_score)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(
            RiskClassification.risk_score.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    # ── Posture Report ──────────────────────────────────────────────

    @staticmethod
    async def generate_posture_report(
        session: AsyncSession,
    ) -> dict[str, Any]:
        """Generate an AI security posture report across all discovered services.

        Returns a summary dict with overall posture score, breakdown by tier,
        department stats, and top risks.
        """
        # Gather all services and classifications
        svc_result = await session.exec(select(DiscoveredService))
        services = list(svc_result.all())

        cls_result = await session.exec(select(RiskClassification))
        classifications = list(cls_result.all())

        total_services = len(services)
        sanctioned = sum(1 for s in services if s.is_sanctioned)
        unsanctioned = total_services - sanctioned

        # Tier breakdown
        tier_counts: dict[str, int] = {
            "critical": 0, "high": 0, "medium": 0, "low": 0, "informational": 0,
        }
        total_risk_score = 0
        for c in classifications:
            tier_counts[c.risk_tier] = tier_counts.get(c.risk_tier, 0) + 1
            total_risk_score += c.risk_score

        # Posture score: 100 minus weighted average risk (higher = better)
        avg_risk = total_risk_score / max(len(classifications), 1)
        posture_score = max(0, min(100, round(100 - avg_risk)))

        # Department breakdown
        dept_stats: dict[str, dict[str, int]] = {}
        for s in services:
            dept = s.department or "unassigned"
            if dept not in dept_stats:
                dept_stats[dept] = {"total": 0, "sanctioned": 0, "unsanctioned": 0}
            dept_stats[dept]["total"] += 1
            if s.is_sanctioned:
                dept_stats[dept]["sanctioned"] += 1
            else:
                dept_stats[dept]["unsanctioned"] += 1

        # Top risks: classifications sorted by score desc, top 5
        top_risks = sorted(classifications, key=lambda c: c.risk_score, reverse=True)[:5]

        return {
            "posture_score": posture_score,
            "total_services": total_services,
            "sanctioned": sanctioned,
            "unsanctioned": unsanctioned,
            "risk_tier_breakdown": tier_counts,
            "department_breakdown": dept_stats,
            "top_risks": [
                {
                    "service_id": str(r.service_id),
                    "risk_tier": r.risk_tier,
                    "risk_score": r.risk_score,
                    "policy_violations": r.policy_violations,
                }
                for r in top_risks
            ],
            "classifications_count": len(classifications),
        }


__all__ = [
    "SentinelScanner",
]
