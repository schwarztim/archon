"""API routes for the Archon governance engine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as PField
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.middleware.rbac import check_permission
from app.models.governance import (
    AgentRegistryEntry,
    ApprovalRequest,
    AuditEntry,
    CompliancePolicy,
    ComplianceRecord,
)
from app.secrets.manager import VaultSecretsManager, get_secrets_manager
from app.services.governance import GovernanceEngine
from app.services.governance_service import GovernanceService
from starlette.responses import Response

router = APIRouter(prefix="/governance", tags=["governance"])


# ── Request / response schemas ──────────────────────────────────────


class PolicyCreate(BaseModel):
    """Payload for creating a governance policy."""

    name: str
    description: str | None = None
    framework: str  # SOC2 | GDPR | HIPAA | custom
    version: int = 1
    status: str = "draft"
    severity: str = "medium"
    rules: dict[str, Any] = PField(default_factory=dict)
    enforcement_action: str = "warn"
    created_by: UUID | None = None


class PolicyUpdate(BaseModel):
    """Payload for partial-updating a governance policy."""

    name: str | None = None
    description: str | None = None
    framework: str | None = None
    version: int | None = None
    status: str | None = None
    severity: str | None = None
    rules: dict[str, Any] | None = None
    enforcement_action: str | None = None


class ComplianceCheckRequest(BaseModel):
    """Payload for requesting a compliance check."""

    agent_id: UUID
    policy_id: UUID | None = None


class AuditEventCreate(BaseModel):
    """Payload for logging an audit event."""

    action: str
    resource_type: str
    resource_id: UUID | None = None
    actor_id: UUID | None = None
    agent_id: UUID | None = None
    outcome: str = "success"
    details: dict[str, Any] | None = None


class AgentRegistryCreate(BaseModel):
    """Payload for registering an agent in the governance registry."""

    agent_id: UUID
    owner: str
    department: str
    approval_status: str = "draft"
    models_used: list[str] = PField(default_factory=list)
    data_accessed: list[str] = PField(default_factory=list)
    risk_level: str = "low"
    sunset_date: datetime | None = None
    extra_metadata: dict[str, Any] = PField(default_factory=dict)


class AgentRegistryUpdate(BaseModel):
    """Payload for updating an agent's governance registry entry."""

    owner: str | None = None
    department: str | None = None
    approval_status: str | None = None
    models_used: list[str] | None = None
    data_accessed: list[str] | None = None
    risk_level: str | None = None
    sunset_date: datetime | None = None
    extra_metadata: dict[str, Any] | None = None


class ApprovalCreate(BaseModel):
    """Payload for creating an approval request."""

    agent_id: UUID
    agent_name: str = ""
    action: str = "promote_to_production"
    approval_rule: str = "any_one"  # any_one | all | majority
    reviewers: list[str] = PField(default_factory=list)
    comment: str | None = None


class ApprovalDecision(BaseModel):
    """Payload for approve/reject decision."""

    comment: str = ""


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Policy CRUD ─────────────────────────────────────────────────────


@router.get("/policies")
async def list_policies(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    framework: str | None = Query(default=None),
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List governance policies with pagination."""
    policies, total = await GovernanceEngine.list_policies(
        session, framework=framework, status=status, limit=limit, offset=offset,
    )
    return {
        "data": [p.model_dump(mode="json") for p in policies],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/policies", status_code=201)
async def create_policy(
    body: PolicyCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new governance policy."""
    policy = CompliancePolicy(**body.model_dump())
    created = await GovernanceEngine.create_policy(session, policy)
    return {"data": created.model_dump(mode="json"), "meta": _meta()}


@router.get("/policies/{policy_id}")
async def get_policy(
    policy_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a governance policy by ID."""
    policy = await GovernanceEngine.get_policy(session, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    return {"data": policy.model_dump(mode="json"), "meta": _meta()}


@router.put("/policies/{policy_id}")
async def update_policy(
    policy_id: UUID,
    body: PolicyUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update a governance policy."""
    data = body.model_dump(exclude_unset=True)
    policy = await GovernanceEngine.update_policy(session, policy_id, data)
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    return {"data": policy.model_dump(mode="json"), "meta": _meta()}


@router.delete("/policies/{policy_id}", status_code=204, response_class=Response)
async def delete_policy(
    policy_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a governance policy."""
    deleted = await GovernanceEngine.delete_policy(session, policy_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Policy not found")
    return Response(status_code=204)


# ── Compliance ──────────────────────────────────────────────────────


@router.post("/compliance/check")
async def check_compliance(
    body: ComplianceCheckRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Run compliance checks for an agent against policies."""
    records = await GovernanceEngine.check_compliance(
        session, agent_id=body.agent_id, policy_id=body.policy_id,
    )
    return {
        "data": [r.model_dump(mode="json") for r in records],
        "meta": _meta(),
    }


# ── Audit Trail ─────────────────────────────────────────────────────


@router.post("/audit", status_code=201)
async def log_audit_event(
    body: AuditEventCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Log a governance audit event."""
    entry = await GovernanceEngine.log_audit_event(
        session,
        action=body.action,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        actor_id=body.actor_id,
        agent_id=body.agent_id,
        outcome=body.outcome,
        details=body.details,
    )
    return {"data": entry.model_dump(mode="json"), "meta": _meta()}


@router.get("/audit")
async def get_audit_trail(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    agent_id: UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Query the governance audit trail with filters."""
    entries, total = await GovernanceEngine.get_audit_trail(
        session,
        agent_id=agent_id,
        action=action,
        resource_type=resource_type,
        outcome=outcome,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [e.model_dump(mode="json") for e in entries],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


# ── Agent Registry ──────────────────────────────────────────────────


@router.post("/agents", status_code=201)
async def register_agent(
    body: AgentRegistryCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Register an agent in the governance registry."""
    entry = AgentRegistryEntry(**body.model_dump())
    created = await GovernanceEngine.register_agent(session, entry)
    return {"data": created.model_dump(mode="json"), "meta": _meta()}


@router.get("/agents")
async def list_registered_agents(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    department: str | None = Query(default=None),
    approval_status: str | None = Query(default=None),
    risk_level: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List agents in the governance registry with pagination."""
    entries, total = await GovernanceEngine.list_registered_agents(
        session,
        department=department,
        approval_status=approval_status,
        risk_level=risk_level,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [e.model_dump(mode="json") for e in entries],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/agents/{agent_id}")
async def get_agent_registration(
    agent_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get an agent's governance registry entry."""
    entry = await GovernanceEngine.get_agent_registration(session, agent_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Agent not found in governance registry")
    return {"data": entry.model_dump(mode="json"), "meta": _meta()}


@router.put("/agents/{agent_id}")
async def update_agent_registration(
    agent_id: UUID,
    body: AgentRegistryUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update an agent's governance registry entry."""
    data = body.model_dump(exclude_unset=True)
    entry = await GovernanceEngine.update_agent_registration(session, agent_id, data)
    if entry is None:
        raise HTTPException(status_code=404, detail="Agent not found in governance registry")
    return {"data": entry.model_dump(mode="json"), "meta": _meta()}


# ── Registry Detail with Compliance History ─────────────────────────


@router.get("/registry")
async def list_registry(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    department: str | None = Query(default=None),
    approval_status: str | None = Query(default=None),
    risk_level: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """List agents with compliance status for the registry dashboard."""
    entries, total = await GovernanceEngine.list_registered_agents(
        session,
        department=department,
        approval_status=approval_status,
        risk_level=risk_level,
        limit=limit,
        offset=offset,
    )

    # Enrich with compliance data
    enriched: list[dict[str, Any]] = []
    for entry in entries:
        detail = await GovernanceEngine.get_agent_detail(session, entry.agent_id)
        if detail:
            enriched.append({
                **entry.model_dump(mode="json"),
                "compliance_status": detail["compliance_status"],
                "compliance_score": detail["compliance_score"],
                "risk_score": detail["risk_score"],
                "total_scans": detail["total_scans"],
            })
        else:
            enriched.append({
                **entry.model_dump(mode="json"),
                "compliance_status": "unknown",
                "compliance_score": 0.0,
                "risk_score": 50,
                "total_scans": 0,
            })

    return {
        "data": enriched,
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/registry/{agent_id}")
async def get_registry_detail(
    agent_id: UUID,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get agent detail with compliance history timeline."""
    detail = await GovernanceEngine.get_agent_detail(session, agent_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Agent not found in governance registry")
    return {"data": detail, "meta": _meta()}


# ── Compliance Scan ─────────────────────────────────────────────────


@router.post("/scan/{agent_id}")
async def scan_agent(
    agent_id: UUID,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Run compliance scan against all active policies for an agent."""
    check_permission(user, "governance", "create")
    result = await GovernanceEngine.scan_agent(session, agent_id)

    # Audit log the scan
    await GovernanceEngine.log_audit_event(
        session,
        action="compliance_scan.executed",
        resource_type="agent",
        resource_id=agent_id,
        actor_id=UUID(user.id) if user.id else None,
        outcome="success",
        details={"compliance_score": result["compliance_score"]},
    )

    return {"data": result, "meta": _meta()}


# ── Approval Workflows ──────────────────────────────────────────────


@router.get("/approvals")
async def list_approvals(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """List approval requests with optional filters."""
    approvals, total = await GovernanceEngine.list_approvals(
        session, status=status, agent_id=agent_id, limit=limit, offset=offset,
    )
    return {
        "data": [a.model_dump(mode="json") for a in approvals],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/approvals", status_code=201)
async def create_approval(
    body: ApprovalCreate,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Create an approval request for agent production promotion."""
    check_permission(user, "governance", "create")
    approval = ApprovalRequest(
        agent_id=body.agent_id,
        requester_id=UUID(user.id) if user.id else None,
        requester_name=user.email,
        agent_name=body.agent_name,
        action=body.action,
        approval_rule=body.approval_rule,
        reviewers=body.reviewers,
        comment=body.comment,
    )
    created = await GovernanceEngine.create_approval(session, approval)

    await GovernanceEngine.log_audit_event(
        session,
        action="approval.created",
        resource_type="approval_request",
        resource_id=created.id,
        actor_id=UUID(user.id) if user.id else None,
        outcome="success",
        details={"agent_id": str(body.agent_id), "action": body.action},
    )

    return {"data": created.model_dump(mode="json"), "meta": _meta()}


@router.post("/approvals/{approval_id}/approve")
async def approve_request(
    approval_id: UUID,
    body: ApprovalDecision,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Approve an approval request."""
    check_permission(user, "governance", "update")
    result = await GovernanceEngine.approve_request(
        session, approval_id, reviewer=user.email, comment=body.comment,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Approval request not found")

    await GovernanceEngine.log_audit_event(
        session,
        action="approval.approved",
        resource_type="approval_request",
        resource_id=approval_id,
        actor_id=UUID(user.id) if user.id else None,
        outcome="success",
        details={"comment": body.comment},
    )

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router.post("/approvals/{approval_id}/reject")
async def reject_request(
    approval_id: UUID,
    body: ApprovalDecision,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Reject an approval request."""
    check_permission(user, "governance", "update")
    result = await GovernanceEngine.reject_request(
        session, approval_id, reviewer=user.email, comment=body.comment,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Approval request not found")

    await GovernanceEngine.log_audit_event(
        session,
        action="approval.rejected",
        resource_type="approval_request",
        resource_id=approval_id,
        actor_id=UUID(user.id) if user.id else None,
        outcome="success",
        details={"comment": body.comment},
    )

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


# ── Enterprise Governance Routes (GovernanceService) ────────────────


class AccessReviewCreate(BaseModel):
    """Payload for creating an access review."""

    review_cycle: str = "quarterly"
    reviewer_id: str | None = None
    reviewee_id: str = ""


class ReviewDecisionPayload(BaseModel):
    """Payload for a single review decision."""

    user_id: str
    resource: str
    decision: str  # approve | revoke | modify
    notes: str = ""


class ReviewDecisionsRequest(BaseModel):
    """Payload for processing review decisions."""

    decisions: list[ReviewDecisionPayload]


class ElevationCreate(BaseModel):
    """Payload for requesting privilege elevation."""

    role: str
    justification: str
    duration_hours: int = PField(default=1, ge=1, le=72)


class ApprovalWorkflowCreate(BaseModel):
    """Payload for creating an approval workflow."""

    agent_id: UUID
    workflow_type: str


class OPAPolicyRequest(BaseModel):
    """Payload for managing OPA policies."""

    action: str = "create"  # create | update | delete | get
    id: UUID | None = None
    name: str = ""
    rego_content: str = ""
    description: str = ""
    active: bool = True


class ReportRequest(BaseModel):
    """Payload for generating a governance report."""

    report_type: str
    period: str


class AuditTrailFilters(BaseModel):
    """Query filters for audit trail."""

    action: str | None = None
    resource_type: str | None = None
    agent_id: UUID | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = PField(default=20, ge=1, le=100)
    offset: int = PField(default=0, ge=0)


@router.post("/access-reviews", status_code=201)
async def create_access_review(
    body: AccessReviewCreate,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Create a periodic access review with reviewer assignment."""
    config = body.model_dump()
    if config.get("reviewer_id") is None:
        config["reviewer_id"] = user.id
    review = await GovernanceService.create_access_review(
        user.tenant_id, user, config, session,
    )
    return {"data": review.model_dump(mode="json"), "meta": _meta()}


@router.post("/access-reviews/{review_id}/decide", status_code=200)
async def process_review_decision(
    review_id: UUID,
    body: ReviewDecisionsRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Process approve/revoke/modify decisions for an access review."""
    decisions = [d.model_dump() for d in body.decisions]
    review = await GovernanceService.process_review_decision(
        user.tenant_id, user, review_id, decisions, session,
    )
    return {"data": review.model_dump(mode="json"), "meta": _meta()}


@router.post("/elevation", status_code=201)
async def request_privilege_elevation(
    body: ElevationCreate,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Request JIT privilege elevation with time limit."""
    elevation = await GovernanceService.request_privilege_elevation(
        user.tenant_id, user, body.role, body.justification,
        body.duration_hours, session,
    )
    return {"data": elevation.model_dump(mode="json"), "meta": _meta()}


@router.get("/compliance/{framework}")
async def get_compliance_status(
    framework: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Get compliance status for a framework (SOC2/GDPR/HIPAA/PCI)."""
    check_permission(user, "governance", "read")
    status = await GovernanceService.get_compliance_status(
        user.tenant_id, framework, session,
    )
    return {"data": status.model_dump(mode="json"), "meta": _meta()}


@router.post("/approvals", status_code=201)
async def create_approval_workflow(
    body: ApprovalWorkflowCreate,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Create a multi-stage approval workflow."""
    workflow = await GovernanceService.create_approval_workflow(
        user.tenant_id, user, body.agent_id, body.workflow_type, session,
    )
    return {"data": workflow.model_dump(mode="json"), "meta": _meta()}


@router.post("/policies/opa", status_code=201)
async def manage_opa_policy(
    body: OPAPolicyRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Manage OPA policies with rego linting."""
    policy_data = body.model_dump()
    policy = await GovernanceService.manage_opa_policy(
        user.tenant_id, user, body.action, policy_data, session,
    )
    return {"data": policy.model_dump(mode="json"), "meta": _meta()}


@router.post("/reports", status_code=201)
async def generate_governance_report(
    body: ReportRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Generate an executive-ready governance report."""
    report = await GovernanceService.generate_governance_report(
        user.tenant_id, user, body.report_type, body.period, session,
    )
    return {"data": report.model_dump(mode="json"), "meta": _meta()}


@router.get("/audit/verified")
async def get_verified_audit_trail(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Query audit trail with hash-chain verification."""
    check_permission(user, "governance", "read")
    filters: dict[str, Any] = {
        "action": action,
        "resource_type": resource_type,
        "agent_id": agent_id,
        "since": since,
        "until": until,
        "limit": limit,
        "offset": offset,
    }
    entries = await GovernanceService.get_audit_trail(
        user.tenant_id, filters, session,
    )
    return {
        "data": [e.model_dump(mode="json") for e in entries],
        "meta": _meta(pagination={"total": len(entries), "limit": limit, "offset": offset}),
    }


# Standalone risk route (outside /governance prefix, at /agents/{id}/risk)
risk_router = APIRouter(tags=["governance"])


@risk_router.get("/agents/{agent_id}/risk")
async def get_agent_risk(
    agent_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Compute and return risk assessment for an agent."""
    check_permission(user, "governance", "read")
    assessment = await GovernanceService.compute_risk_score(
        user.tenant_id, agent_id, session,
    )
    return {"data": assessment.model_dump(mode="json"), "meta": _meta()}
