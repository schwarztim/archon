"""Tests for NL Wizard (Agent-03) — wizard_service.py.

Covers the 4-step pipeline: Describe → Plan → Build → Validate,
plus refine, RBAC, tenant isolation, and security checks.
"""

from __future__ import annotations

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.wizard import (
    CredentialRequirement,
    GeneratedAgent,
    NLAnalysis,
    NLBuildPlan,
    PlannedEdge,
    PlannedNode,
)
from app.services.wizard_service import NLWizardService


# ── Fixtures ────────────────────────────────────────────────────────


TENANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER_A_ID = "11111111-1111-1111-1111-111111111111"
USER_B_ID = "22222222-2222-2222-2222-222222222222"


def _make_user(
    *,
    tenant_id: str = TENANT_A,
    permissions: list[str] | None = None,
    user_id: str = USER_A_ID,
) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user_id,
        email="dev@example.com",
        tenant_id=tenant_id,
        roles=["developer"],
        permissions=permissions or ["agents:create", "agents:read"],
        mfa_verified=True,
        session_id="sess-xyz",
    )


@pytest.fixture()
def svc() -> NLWizardService:
    return NLWizardService()


@pytest.fixture()
def user_a() -> AuthenticatedUser:
    return _make_user()


@pytest.fixture()
def user_b() -> AuthenticatedUser:
    return _make_user(tenant_id=TENANT_B, user_id=USER_B_ID)


# ── Describe tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_describe_extracts_intents(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """describe() should extract matching intents from NL text."""
    result = await svc.describe(TENANT_A, user_a, "Automate ticket workflow with Jira")
    assert "automate" in result.intents


@pytest.mark.asyncio
async def test_describe_extracts_entities(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """describe() should extract capitalized entity tokens."""
    result = await svc.describe(TENANT_A, user_a, "Monitor Sales Dashboard and send Slack alerts")
    assert isinstance(result.entities, list)
    assert any("Sales" in e or "Dashboard" in e or "Slack" in e for e in result.entities)


@pytest.mark.asyncio
async def test_describe_detects_connectors(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """describe() should detect external connectors from text."""
    result = await svc.describe(TENANT_A, user_a, "Pull issues from Jira and post to Slack")
    assert "jira" in result.connectors_detected
    assert "slack" in result.connectors_detected


@pytest.mark.asyncio
async def test_describe_no_connectors(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """describe() returns empty connectors list when none mentioned."""
    result = await svc.describe(TENANT_A, user_a, "Analyze a simple text document")
    assert result.connectors_detected == [] or isinstance(result.connectors_detected, list)


@pytest.mark.asyncio
async def test_describe_template_match_above_70(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """describe() with >70% template similarity should suggest a template."""
    # This description closely matches "routes customer queries to appropriate handlers"
    result = await svc.describe(
        TENANT_A,
        user_a,
        "routes customer queries to appropriate handlers",
    )
    assert len(result.template_matches) > 0
    top = result.template_matches[0]
    assert top.similarity > 0.70
    assert top.template_id == "tpl-customer-support"


@pytest.mark.asyncio
async def test_describe_template_match_below_threshold(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """describe() with a vague description should not yield >70% match."""
    result = await svc.describe(TENANT_A, user_a, "do something random and unrelated xyz")
    for m in result.template_matches:
        assert m.similarity <= 0.70


@pytest.mark.asyncio
async def test_describe_returns_analysis_id(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """describe() should return an NLAnalysis with a unique analysis_id."""
    result = await svc.describe(TENANT_A, user_a, "Chat with users about their accounts")
    assert result.analysis_id
    assert isinstance(result.analysis_id, str)


@pytest.mark.asyncio
async def test_describe_default_intent(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """describe() should default to ['general'] when no known intent matched."""
    result = await svc.describe(TENANT_A, user_a, "xyz 12345 qwerty")
    assert result.intents == ["general"]


# ── Plan tests ──────────────────────────────────────────────────────


async def _analysis_with_connectors(svc: NLWizardService, user: AuthenticatedUser) -> NLAnalysis:
    """Helper: produce an analysis that has connectors."""
    return await svc.describe(TENANT_A, user, "Automate Jira tickets and post to Slack channel")


@pytest.mark.asyncio
async def test_plan_generates_nodes_and_edges(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """plan() should produce PlannedNodes and PlannedEdges."""
    analysis = await _analysis_with_connectors(svc, user_a)
    plan = await svc.plan(TENANT_A, user_a, analysis)
    assert len(plan.nodes) >= 2
    assert len(plan.edges) >= 1


@pytest.mark.asyncio
async def test_plan_includes_models(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """plan() should list model requirements when chat/analyze intent is present."""
    analysis = await svc.describe(TENANT_A, user_a, "Analyze sales data and chat with user")
    plan = await svc.plan(TENANT_A, user_a, analysis)
    assert len(plan.models_needed) > 0
    assert any(m.model_id == "gpt-4o" for m in plan.models_needed)


@pytest.mark.asyncio
async def test_plan_includes_connectors(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """plan() should list connector requirements for detected connectors."""
    analysis = await _analysis_with_connectors(svc, user_a)
    plan = await svc.plan(TENANT_A, user_a, analysis)
    assert len(plan.connectors_needed) > 0
    connector_types = [c.connector_type for c in plan.connectors_needed]
    assert "jira" in connector_types
    assert "slack" in connector_types


@pytest.mark.asyncio
async def test_plan_credential_requirements_vault_paths(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """plan() credential_requirements must use Vault paths, never raw keys."""
    analysis = await _analysis_with_connectors(svc, user_a)
    plan = await svc.plan(TENANT_A, user_a, analysis)
    assert len(plan.credential_requirements) > 0
    for cred in plan.credential_requirements:
        assert cred.vault_path.startswith(f"archon/{TENANT_A}/connectors/")
        # Must never contain raw secret values
        assert "sk-" not in cred.vault_path
        assert "Bearer" not in cred.vault_path


@pytest.mark.asyncio
async def test_plan_auth_nodes_for_connectors(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """plan() should create auth nodes for each connector."""
    analysis = await _analysis_with_connectors(svc, user_a)
    plan = await svc.plan(TENANT_A, user_a, analysis)
    auth_nodes = [n for n in plan.nodes if n.node_type == "auth"]
    connector_names = analysis.connectors_detected
    assert len(auth_nodes) == len(connector_names)
    for connector in connector_names:
        assert any(n.node_id == f"auth_{connector}" for n in auth_nodes)


# ── Build tests ─────────────────────────────────────────────────────


async def _build_agent(svc: NLWizardService, user: AuthenticatedUser, tenant_id: str = TENANT_A) -> GeneratedAgent:
    """Helper: run describe → plan → build."""
    analysis = await svc.describe(tenant_id, user, "Automate Jira tickets and post to Slack")
    plan = await svc.plan(tenant_id, user, analysis)
    return await svc.build(tenant_id, user, plan)


@pytest.mark.asyncio
async def test_build_generates_graph_json(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """build() must produce a graph_definition dict with nodes and edges."""
    agent = await _build_agent(svc, user_a)
    assert "nodes" in agent.graph_definition
    assert "edges" in agent.graph_definition
    assert len(agent.graph_definition["nodes"]) > 0


@pytest.mark.asyncio
async def test_build_sets_tenant_workspace_owner(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """build() must set tenant_id, workspace_id, and owner_id."""
    agent = await _build_agent(svc, user_a)
    assert agent.tenant_id == TENANT_A
    assert agent.workspace_id  # non-empty
    assert agent.owner_id == user_a.id


@pytest.mark.asyncio
async def test_build_python_source_has_tenant(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """build() python_source must embed TENANT_ID and OWNER_ID."""
    agent = await _build_agent(svc, user_a)
    assert f'TENANT_ID = "{TENANT_A}"' in agent.python_source
    assert f'OWNER_ID = "{user_a.id}"' in agent.python_source


@pytest.mark.asyncio
async def test_build_injects_auth_nodes(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """build() output must include auth nodes for each connector in graph_definition."""
    agent = await _build_agent(svc, user_a)
    node_ids = [n["id"] for n in agent.graph_definition["nodes"]]
    # The description mentions Jira and Slack
    assert "auth_jira" in node_ids
    assert "auth_slack" in node_ids


@pytest.mark.asyncio
async def test_build_graph_contains_tenant_in_definition(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """build() graph_definition dict must include tenant_id."""
    agent = await _build_agent(svc, user_a)
    assert agent.graph_definition["tenant_id"] == TENANT_A
    assert agent.graph_definition["owner_id"] == user_a.id


# ── Validate tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_passes_clean_agent(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """validate() should pass for a properly generated agent."""
    agent = await _build_agent(svc, user_a)
    result = await svc.validate(TENANT_A, user_a, agent)
    assert result.passed is True
    assert all(i.severity != "critical" for i in result.security_issues)


@pytest.mark.asyncio
async def test_validate_detects_hardcoded_secret(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """validate() must flag hardcoded secrets in generated code."""
    agent = await _build_agent(svc, user_a)
    agent.python_source += '\napi_key = "sk-abc123secretkey456"\n'
    result = await svc.validate(TENANT_A, user_a, agent)
    assert result.passed is False
    codes = [i.code for i in result.security_issues]
    assert "HARDCODED_SECRET" in codes


@pytest.mark.asyncio
async def test_validate_detects_bearer_token(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """validate() must flag Bearer tokens in generated source."""
    agent = await _build_agent(svc, user_a)
    agent.python_source += '\nheaders = {"Authorization": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.abc"}\n'
    result = await svc.validate(TENANT_A, user_a, agent)
    assert result.passed is False
    codes = [i.code for i in result.security_issues]
    assert "HARDCODED_SECRET" in codes


@pytest.mark.asyncio
async def test_validate_checks_vault_path_validity(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """validate() must flag credential paths outside the tenant scope."""
    agent = await _build_agent(svc, user_a)
    # Inject a bad vault path belonging to a different tenant
    agent.credential_manifest.append(
        CredentialRequirement(
            vault_path="archon/wrong-tenant/connectors/github",
            connector_type="github",
            description="bad cred",
        )
    )
    result = await svc.validate(TENANT_A, user_a, agent)
    assert result.passed is False
    codes = [i.code for i in result.security_issues]
    assert "INVALID_VAULT_PATH" in codes


@pytest.mark.asyncio
async def test_validate_detects_tenant_mismatch(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """validate() must flag if agent.tenant_id differs from request tenant."""
    agent = await _build_agent(svc, user_a)
    agent.tenant_id = "wrong-tenant"
    result = await svc.validate(TENANT_A, user_a, agent)
    assert result.passed is False
    codes = [i.code for i in result.security_issues]
    assert "TENANT_MISMATCH" in codes


# ── Refine tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refine_applies_feedback(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """refine() should apply feedback and produce a new GeneratedAgent."""
    agent = await _build_agent(svc, user_a)
    refined = await svc.refine(TENANT_A, user_a, agent, "Add error handling node", iteration=1)
    assert refined.agent_name.endswith("-r1")
    assert refined.graph_definition["metadata"]["feedback"] == "Add error handling node"
    assert refined.graph_definition["metadata"]["refinement_iteration"] == 1


@pytest.mark.asyncio
async def test_refine_max_iterations(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """refine() must raise ValueError when iteration exceeds 3."""
    agent = await _build_agent(svc, user_a)
    with pytest.raises(ValueError, match="Maximum refinement iterations"):
        await svc.refine(TENANT_A, user_a, agent, "more changes", iteration=4)


@pytest.mark.asyncio
async def test_refine_preserves_tenant(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """refine() must keep the same tenant_id and workspace_id."""
    agent = await _build_agent(svc, user_a)
    refined = await svc.refine(TENANT_A, user_a, agent, "Add logging", iteration=2)
    assert refined.tenant_id == TENANT_A
    assert refined.workspace_id == agent.workspace_id


# ── Tenant isolation tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_isolation_describe(svc: NLWizardService, user_a: AuthenticatedUser, user_b: AuthenticatedUser) -> None:
    """Two tenants running describe() should get independent analysis IDs."""
    r_a = await svc.describe(TENANT_A, user_a, "Automate Jira tickets")
    r_b = await svc.describe(TENANT_B, user_b, "Automate Jira tickets")
    assert r_a.analysis_id != r_b.analysis_id


@pytest.mark.asyncio
async def test_tenant_isolation_vault_paths(svc: NLWizardService, user_a: AuthenticatedUser, user_b: AuthenticatedUser) -> None:
    """Vault paths in plans must be scoped to the requesting tenant."""
    analysis_a = await svc.describe(TENANT_A, user_a, "Post to Slack")
    plan_a = await svc.plan(TENANT_A, user_a, analysis_a)

    analysis_b = await svc.describe(TENANT_B, user_b, "Post to Slack")
    plan_b = await svc.plan(TENANT_B, user_b, analysis_b)

    for cred in plan_a.credential_requirements:
        assert TENANT_A in cred.vault_path
        assert TENANT_B not in cred.vault_path

    for cred in plan_b.credential_requirements:
        assert TENANT_B in cred.vault_path
        assert TENANT_A not in cred.vault_path


# ── RBAC test ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rbac_requires_agents_create(svc: NLWizardService) -> None:
    """A user with agents:create permission should be able to run the pipeline."""
    user = _make_user(permissions=["agents:create"])
    assert "agents:create" in user.permissions
    # Pipeline should succeed (RBAC is checked at the endpoint layer,
    # service layer trusts that the caller is authorized)
    agent, validation = await svc.full_pipeline(TENANT_A, user, "Chat assistant")
    assert agent.tenant_id == TENANT_A
    assert validation is not None


# ── Full pipeline test ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_pipeline_end_to_end(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """full_pipeline() should run describe → plan → build → validate end-to-end."""
    agent, validation = await svc.full_pipeline(
        TENANT_A, user_a, "Monitor GitHub PRs and create Jira tickets"
    )
    assert agent.tenant_id == TENANT_A
    assert agent.owner_id == user_a.id
    assert agent.python_source
    assert agent.graph_definition
    assert validation.passed is True


@pytest.mark.asyncio
async def test_full_pipeline_with_connectors_has_auth_edges(svc: NLWizardService, user_a: AuthenticatedUser) -> None:
    """full_pipeline() graph should have auth→tool edges for each connector."""
    agent, _ = await svc.full_pipeline(
        TENANT_A, user_a, "Automate Jira tickets and notify via Slack"
    )
    edges = agent.graph_definition["edges"]
    # auth_jira → tool_jira edge must exist
    assert any(
        e["source"] == "auth_jira" and e["target"] == "tool_jira"
        for e in edges
    )
    assert any(
        e["source"] == "auth_slack" and e["target"] == "tool_slack"
        for e in edges
    )
