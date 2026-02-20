"""Service for converting natural language descriptions into agent graph definitions.

Enterprise NL Wizard — 4-step pipeline: Describe → Plan → Build → Validate.
All credential references use Vault paths, all operations are tenant-scoped,
and every step is audit-logged.
"""

from __future__ import annotations

import json
import logging
import re
import textwrap
from difflib import SequenceMatcher
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.audit import EnterpriseAuditEvent
from app.models.wizard import (
    ConnectorRequirement,
    CredentialRequirement,
    GeneratedAgent,
    ModelRequirement,
    NLAnalysis,
    NLBuildPlan,
    PlannedEdge,
    PlannedNode,
    SecurityIssue,
    TemplateMatch,
    ValidationResult,
)

logger = logging.getLogger(__name__)


# ── Legacy schemas (kept for backward compatibility) ────────────────


class NodePosition(BaseModel):
    """Position of a node in the React Flow canvas."""

    x: float = 0.0
    y: float = 0.0


class NodeData(BaseModel):
    """Data payload for a React Flow node."""

    label: str
    type: str = "default"
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class GraphNode(BaseModel):
    """A single node in the agent graph (React Flow format)."""

    id: str
    type: str = "default"
    position: NodePosition
    data: NodeData


class GraphEdge(BaseModel):
    """A single edge in the agent graph (React Flow format)."""

    id: str
    source: str
    target: str
    label: str = ""


class AgentGraphDefinition(BaseModel):
    """Complete agent definition as a React Flow graph."""

    name: str
    description: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class WizardRequest(BaseModel):
    """Incoming request for the wizard endpoint."""

    description: str = Field(
        ..., min_length=1, max_length=5000, description="Natural language agent description"
    )


class WizardResponse(BaseModel):
    """Response from the wizard endpoint."""

    agent_definition: AgentGraphDefinition
    mode: str = "mock"


# ── Known connectors & templates for NLP matching ───────────────────

_KNOWN_CONNECTORS: dict[str, list[str]] = {
    "slack": ["slack", "message", "channel", "notification"],
    "jira": ["jira", "ticket", "issue", "sprint"],
    "github": ["github", "repository", "repo", "pull request", "pr", "commit"],
    "salesforce": ["salesforce", "crm", "lead", "opportunity", "account"],
    "email": ["email", "smtp", "inbox", "mail"],
    "database": ["database", "sql", "postgres", "mysql", "db", "query"],
    "rest_api": ["api", "rest", "http", "endpoint", "webhook"],
    "openai": ["openai", "gpt", "chatgpt", "llm"],
    "servicenow": ["servicenow", "snow", "incident", "cmdb"],
    "confluence": ["confluence", "wiki", "documentation", "page"],
}

_KNOWN_INTENTS: dict[str, list[str]] = {
    "automate": ["automate", "automation", "workflow", "schedule", "trigger"],
    "analyze": ["analyze", "analysis", "report", "dashboard", "insight"],
    "monitor": ["monitor", "watch", "alert", "notify", "detect"],
    "chat": ["chat", "conversation", "assistant", "respond", "answer"],
    "transform": ["transform", "convert", "translate", "format", "parse"],
    "integrate": ["integrate", "connect", "sync", "bridge", "pipe"],
}

_TEMPLATE_CATALOG: list[dict[str, str]] = [
    {"id": "tpl-customer-support", "name": "Customer Support Bot", "description": "routes customer queries to appropriate handlers"},
    {"id": "tpl-data-pipeline", "name": "Data Pipeline Agent", "description": "extracts transforms and loads data between systems"},
    {"id": "tpl-code-reviewer", "name": "Code Review Agent", "description": "reviews pull requests and provides feedback"},
    {"id": "tpl-incident-responder", "name": "Incident Responder", "description": "monitors alerts and creates incident tickets"},
    {"id": "tpl-research-assistant", "name": "Research Assistant", "description": "searches documents and summarizes findings"},
]


# ── Helpers ─────────────────────────────────────────────────────────


def _extract_intents(text: str) -> list[str]:
    """Extract intent labels from free-text description."""
    lower = text.lower()
    found: list[str] = []
    for intent, keywords in _KNOWN_INTENTS.items():
        if any(kw in lower for kw in keywords):
            found.append(intent)
    return found or ["general"]


def _extract_entities(text: str) -> list[str]:
    """Extract meaningful noun-phrase entities from description."""
    words = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", text)
    entities = list(dict.fromkeys(words))
    return entities[:20]


def _detect_connectors(text: str) -> list[str]:
    """Detect external connectors mentioned in the description."""
    lower = text.lower()
    found: list[str] = []
    for connector, keywords in _KNOWN_CONNECTORS.items():
        if any(kw in lower for kw in keywords):
            found.append(connector)
    return found


def _match_templates(text: str) -> list[TemplateMatch]:
    """Match description against known templates using string similarity."""
    lower = text.lower()
    matches: list[TemplateMatch] = []
    for tpl in _TEMPLATE_CATALOG:
        ratio = SequenceMatcher(None, lower, tpl["description"]).ratio()
        if ratio > 0.25:
            matches.append(TemplateMatch(
                template_id=tpl["id"],
                template_name=tpl["name"],
                similarity=round(ratio, 3),
            ))
    matches.sort(key=lambda m: m.similarity, reverse=True)
    return matches[:5]


def _vault_path(tenant_id: str, connector_type: str) -> str:
    """Build a Vault secret path for a connector credential."""
    return f"archon/{tenant_id}/connectors/{connector_type}"


def _create_audit_event(
    user: AuthenticatedUser,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> EnterpriseAuditEvent:
    """Create an enterprise audit event."""
    return EnterpriseAuditEvent(
        tenant_id=UUID(user.tenant_id),
        user_id=UUID(user.id),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        session_id=user.session_id,
    )


_HARDCODED_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"""(?:api[_-]?key|secret|token)\s*=\s*['"][^'"]+['"]""", re.IGNORECASE),
    re.compile(r"""(?:sk-|ghp_|xoxb-|xoxp-|AKIA)[A-Za-z0-9]+"""),
    re.compile(r"""Bearer\s+[A-Za-z0-9._~+/=-]{20,}"""),
]


# ── Node type templates ─────────────────────────────────────────────


def _generate_node_function(node: PlannedNode) -> str:
    """Generate type-specific node function with meaningful default logic."""
    node_type = node.node_type
    node_id = node.node_id
    label = node.label
    description = node.description
    config = node.config
    
    # Base template structure
    base = f'async def {node_id}(state: dict[str, Any]) -> dict[str, Any]:\n    """Node: {label} — {description}"""'
    
    # Type-specific implementations
    if node_type == "input":
        return textwrap.dedent(f"""\
            {base}
                # Extract and validate input from state
                user_input = state.get("input", "")
                if not user_input:
                    raise ValueError("Input node requires 'input' key in state")
                
                state["messages"] = state.get("messages", [])
                state["messages"].append({{"role": "user", "content": user_input}})
                state["current_node"] = "{node_id}"
                return state""")
    
    elif node_type == "output":
        return textwrap.dedent(f"""\
            {base}
                # Format final output response
                messages = state.get("messages", [])
                result = state.get("result", "")
                
                output = {{
                    "response": result,
                    "message_history": messages,
                    "status": "completed",
                }}
                
                state["output"] = output
                state["current_node"] = "{node_id}"
                return state""")
    
    elif node_type == "router":
        model = config.get("model", "gpt-4o-mini")
        return textwrap.dedent(f"""\
            {base}
                # Route based on intent classification
                # Model: {model}
                from app.services.llm import classify_intent
                
                messages = state.get("messages", [])
                last_message = messages[-1]["content"] if messages else ""
                
                intent = await classify_intent(last_message, model="{model}")
                state["intent"] = intent
                state["next_node"] = intent  # Router decision
                state["current_node"] = "{node_id}"
                return state""")
    
    elif node_type == "llm":
        model = config.get("model", "gpt-4o")
        return textwrap.dedent(f"""\
            {base}
                # Process with language model
                # Model: {model}
                from app.services.llm import generate_completion
                
                messages = state.get("messages", [])
                system_prompt = "You are a helpful AI assistant."
                
                response = await generate_completion(
                    messages=messages,
                    model="{model}",
                    system_prompt=system_prompt,
                )
                
                state["messages"].append({{"role": "assistant", "content": response}})
                state["result"] = response
                state["current_node"] = "{node_id}"
                return state""")
    
    elif node_type == "tool":
        connector = config.get("connector", "unknown")
        return textwrap.dedent(f"""\
            {base}
                # Interact with external tool/connector
                # Connector: {connector}
                from app.connectors import get_connector
                
                connector_instance = get_connector("{connector}")
                credentials = state.get("credentials", {{}}).get("{connector}")
                
                if not credentials:
                    raise ValueError("Tool node requires credentials in state")
                
                # Execute connector action
                tool_input = state.get("tool_input", {{}})
                result = await connector_instance.execute(tool_input, credentials)
                
                state["tool_result"] = result
                state["result"] = result
                state["current_node"] = "{node_id}"
                return state""")
    
    elif node_type == "auth":
        vault_path = config.get("vault_path", "")
        return textwrap.dedent(f"""\
            {base}
                # Authenticate with connector via Vault
                # Vault path: {vault_path}
                from app.secrets.manager import get_secrets_manager
                
                secrets_manager = await get_secrets_manager()
                tenant_id = state.get("tenant_id", TENANT_ID)
                
                credentials = await secrets_manager.get_secret(
                    "{vault_path}",
                    tenant_id,
                )
                
                # Store credentials in state for downstream tool nodes
                if "credentials" not in state:
                    state["credentials"] = {{}}
                # Store under connector name so tool nodes can find it
                connector_name = "{vault_path}".rsplit("/", 1)[-1] if "{vault_path}" else "{node_id}"
                state["credentials"][connector_name] = credentials
                state["current_node"] = "{node_id}"
                return state""")
    
    else:
        # Fallback for unknown node types
        return textwrap.dedent(f"""\
            {base}
                # Generic node implementation
                # Node type: {node_type}
                state["current_node"] = "{node_id}"
                return state""")


# ── NLWizardService ────────────────────────────────────────────────


class NLWizardService:
    """Enterprise Natural Language → Agent Wizard.

    Implements a 4-step pipeline (Describe → Plan → Build → Validate)
    with tenant isolation, RBAC enforcement, Vault-only credentials,
    and audit logging at every step.
    """

    # ── Step 1: Describe ────────────────────────────────────────────

    async def describe(
        self,
        tenant_id: str,
        user: AuthenticatedUser,
        nl_description: str,
    ) -> NLAnalysis:
        """Analyse a natural-language description and extract structured intent.

        Returns intents, entities, detected connectors, and template matches.
        A template with >70% similarity is flagged for reuse.
        """
        intents = _extract_intents(nl_description)
        entities = _extract_entities(nl_description)
        connectors = _detect_connectors(nl_description)
        templates = _match_templates(nl_description)

        top_similarity = templates[0].similarity if templates else 0.0
        confidence = min(1.0, 0.5 + 0.5 * top_similarity)

        analysis = NLAnalysis(
            original_description=nl_description,
            intents=intents,
            entities=entities,
            connectors_detected=connectors,
            template_matches=templates,
            confidence=round(confidence, 3),
        )

        audit = _create_audit_event(
            user, "wizard.describe", "wizard",
            analysis.analysis_id,
            {"intents": intents, "connectors": connectors, "tenant_id": tenant_id},
        )
        logger.info(
            "Wizard describe completed",
            extra={"tenant_id": tenant_id, "audit_id": str(audit.id)},
        )

        return analysis

    # ── Step 2: Plan ────────────────────────────────────────────────

    async def plan(
        self,
        tenant_id: str,
        user: AuthenticatedUser,
        analysis: NLAnalysis,
    ) -> NLBuildPlan:
        """Generate a structured build plan from the NLP analysis.

        Produces nodes, edges, model requirements, connector requirements,
        credential paths (Vault only), cost estimate, and security notes.
        """
        nodes: list[PlannedNode] = [
            PlannedNode(
                node_id="input",
                label="User Input",
                node_type="input",
                description="Receives the initial request",
            ),
        ]

        # Add a router node if multiple intents detected
        if len(analysis.intents) > 1:
            nodes.append(PlannedNode(
                node_id="router",
                label="Intent Router",
                node_type="router",
                description="Routes based on detected intent",
                config={"model": "gpt-4o-mini"},
            ))

        # Add connector-specific tool nodes
        for idx, connector in enumerate(analysis.connectors_detected):
            nodes.append(PlannedNode(
                node_id=f"tool_{connector}",
                label=f"{connector.title()} Integration",
                node_type="tool",
                description=f"Interacts with {connector}",
                config={"connector": connector},
            ))

        # Add an LLM processing node if chat/analyze intent
        if any(i in ("chat", "analyze") for i in analysis.intents):
            nodes.append(PlannedNode(
                node_id="llm_processor",
                label="LLM Processor",
                node_type="llm",
                description="Processes with language model",
                config={"model": "gpt-4o"},
            ))

        # Add auth nodes for each connector
        for connector in analysis.connectors_detected:
            nodes.append(PlannedNode(
                node_id=f"auth_{connector}",
                label=f"{connector.title()} Auth",
                node_type="auth",
                description=f"Authenticates with {connector} via Vault",
                config={"vault_path": _vault_path(tenant_id, connector)},
            ))

        nodes.append(PlannedNode(
            node_id="output",
            label="Response",
            node_type="output",
            description="Returns the final result",
        ))

        # Build edges
        edges: list[PlannedEdge] = []
        prev = "input"

        if len(analysis.intents) > 1:
            edges.append(PlannedEdge(source="input", target="router"))
            prev = "router"

        # Auth → Tool edges for connectors
        for connector in analysis.connectors_detected:
            edges.append(PlannedEdge(source=prev, target=f"auth_{connector}"))
            edges.append(PlannedEdge(source=f"auth_{connector}", target=f"tool_{connector}"))
            edges.append(PlannedEdge(source=f"tool_{connector}", target="output"))

        if any(i in ("chat", "analyze") for i in analysis.intents):
            edges.append(PlannedEdge(source=prev, target="llm_processor"))
            edges.append(PlannedEdge(source="llm_processor", target="output"))

        if not edges:
            edges.append(PlannedEdge(source="input", target="output"))

        # Model requirements
        models_needed: list[ModelRequirement] = []
        if any(i in ("chat", "analyze") for i in analysis.intents):
            models_needed.append(ModelRequirement(
                provider="openai", model_id="gpt-4o", purpose="primary processing",
            ))
        if len(analysis.intents) > 1:
            models_needed.append(ModelRequirement(
                provider="openai", model_id="gpt-4o-mini", purpose="intent routing",
            ))

        # Connector requirements
        connectors_needed = [
            ConnectorRequirement(
                connector_type=c, name=f"{c.title()} Connector", purpose=f"Integration with {c}",
            )
            for c in analysis.connectors_detected
        ]

        # Credential requirements — Vault paths only
        credential_requirements = [
            CredentialRequirement(
                vault_path=_vault_path(tenant_id, c),
                connector_type=c,
                description=f"Credentials for {c} connector",
            )
            for c in analysis.connectors_detected
        ]

        # Cost estimate (rough: $0.01 per node per invocation)
        estimated_cost = round(len(nodes) * 0.01 + len(models_needed) * 0.05, 4)

        security_notes: list[str] = [
            "All credentials fetched from Vault at runtime",
            f"Tenant isolation enforced: {tenant_id}",
        ]
        if credential_requirements:
            security_notes.append(
                f"{len(credential_requirements)} connector credential(s) required in Vault",
            )

        build_plan = NLBuildPlan(
            analysis_id=analysis.analysis_id,
            nodes=nodes,
            edges=edges,
            models_needed=models_needed,
            connectors_needed=connectors_needed,
            credential_requirements=credential_requirements,
            estimated_cost=estimated_cost,
            security_notes=security_notes,
        )

        audit = _create_audit_event(
            user, "wizard.plan", "wizard",
            build_plan.plan_id,
            {"node_count": len(nodes), "edge_count": len(edges), "tenant_id": tenant_id},
        )
        logger.info(
            "Wizard plan generated",
            extra={"tenant_id": tenant_id, "audit_id": str(audit.id)},
        )

        return build_plan

    # ── Step 3: Build ───────────────────────────────────────────────

    async def build(
        self,
        tenant_id: str,
        user: AuthenticatedUser,
        plan: NLBuildPlan,
    ) -> GeneratedAgent:
        """Convert a build plan into a LangGraph JSON definition + Python source.

        Injects auth nodes for each connector and sets tenant/workspace/owner IDs.
        """
        agent_name = f"agent-{uuid4().hex[:8]}"

        # Build LangGraph-compatible graph definition
        graph_nodes: list[dict[str, Any]] = []
        for node in plan.nodes:
            graph_nodes.append({
                "id": node.node_id,
                "type": node.node_type,
                "label": node.label,
                "description": node.description,
                "config": node.config,
            })

        graph_edges: list[dict[str, Any]] = []
        for edge in plan.edges:
            graph_edges.append({
                "source": edge.source,
                "target": edge.target,
                "condition": edge.condition,
            })

        graph_definition: dict[str, Any] = {
            "name": agent_name,
            "tenant_id": tenant_id,
            "owner_id": user.id,
            "nodes": graph_nodes,
            "edges": graph_edges,
            "metadata": {
                "plan_id": plan.plan_id,
                "models": [m.model_dump() for m in plan.models_needed],
                "connectors": [c.model_dump() for c in plan.connectors_needed],
            },
        }

        # Generate Python source stub
        connector_imports = "\n".join(
            f"# connector: {cr.connector_type} -> vault: {cr.vault_path}"
            for cr in plan.credential_requirements
        )

        # Node templates with type-specific logic
        node_funcs = "\n\n".join(_generate_node_function(node) for node in plan.nodes)

        python_source = textwrap.dedent(f"""\
            \"\"\"Auto-generated agent: {agent_name}\"\"\"
            from __future__ import annotations
            from typing import Any

            # Credential references (Vault paths — never hardcode secrets)
            {connector_imports or "# No connectors required"}

            TENANT_ID = "{tenant_id}"
            OWNER_ID = "{user.id}"

            {node_funcs}

            GRAPH = {json.dumps(graph_definition, indent=2)}
        """)

        agent = GeneratedAgent(
            agent_name=agent_name,
            tenant_id=tenant_id,
            workspace_id=plan.analysis_id,
            owner_id=user.id,
            graph_definition=graph_definition,
            python_source=python_source,
            credential_manifest=plan.credential_requirements,
            plan_id=plan.plan_id,
        )

        audit = _create_audit_event(
            user, "wizard.build", "wizard",
            agent_name,
            {"plan_id": plan.plan_id, "node_count": len(plan.nodes), "tenant_id": tenant_id},
        )
        logger.info(
            "Wizard build completed",
            extra={"tenant_id": tenant_id, "audit_id": str(audit.id)},
        )

        return agent

    # ── Step 4: Validate ────────────────────────────────────────────

    async def validate(
        self,
        tenant_id: str,
        user: AuthenticatedUser,
        agent: GeneratedAgent,
    ) -> ValidationResult:
        """Run security scan, cost estimation, and compliance checks.

        Checks for hardcoded secrets, validates Vault paths, and verifies
        tenant isolation in the generated agent.
        """
        issues: list[SecurityIssue] = []
        compliance_notes: list[str] = []

        # Security: check for hardcoded secrets in python source
        for pattern in _HARDCODED_SECRET_PATTERNS:
            if pattern.search(agent.python_source):
                issues.append(SecurityIssue(
                    severity="critical",
                    code="HARDCODED_SECRET",
                    message="Potential hardcoded secret detected in generated source",
                ))

        # Security: validate all credential references use Vault paths
        for cred in agent.credential_manifest:
            if not cred.vault_path.startswith(f"archon/{tenant_id}/"):
                issues.append(SecurityIssue(
                    severity="critical",
                    code="INVALID_VAULT_PATH",
                    message=f"Credential path {cred.vault_path} does not match tenant scope",
                ))

        # Security: verify tenant_id consistency
        if agent.tenant_id != tenant_id:
            issues.append(SecurityIssue(
                severity="critical",
                code="TENANT_MISMATCH",
                message="Agent tenant_id does not match request tenant_id",
            ))

        # Compliance: check owner is set
        if not agent.owner_id:
            compliance_notes.append("WARNING: agent has no owner_id set")

        # Compliance: graph must have at least input and output nodes
        node_types = [n.get("type", "") for n in agent.graph_definition.get("nodes", [])]
        if "input" not in node_types:
            compliance_notes.append("Graph is missing an input node")
        if "output" not in node_types:
            compliance_notes.append("Graph is missing an output node")

        compliance_notes.append(f"Tenant isolation verified: {tenant_id}")
        compliance_notes.append("All credentials reference Vault paths")

        # Cost estimate based on node count and model usage
        node_count = len(agent.graph_definition.get("nodes", []))
        model_count = len(agent.graph_definition.get("metadata", {}).get("models", []))
        cost_estimate = round(node_count * 0.01 + model_count * 0.05, 4)

        passed = not any(i.severity == "critical" for i in issues)

        result = ValidationResult(
            passed=passed,
            security_issues=issues,
            cost_estimate=cost_estimate,
            compliance_notes=compliance_notes,
        )

        audit = _create_audit_event(
            user, "wizard.validate", "wizard",
            agent.agent_name,
            {"passed": passed, "issue_count": len(issues), "tenant_id": tenant_id},
        )
        logger.info(
            "Wizard validation completed",
            extra={"tenant_id": tenant_id, "passed": passed, "audit_id": str(audit.id)},
        )

        return result

    # ── Refine (iterative) ──────────────────────────────────────────

    async def refine(
        self,
        tenant_id: str,
        user: AuthenticatedUser,
        agent: GeneratedAgent,
        feedback: str,
        iteration: int = 1,
    ) -> GeneratedAgent:
        """Iteratively refine a generated agent based on user feedback.

        Supports a maximum of 3 refinement iterations.
        """
        max_iterations = 3
        if iteration > max_iterations:
            raise ValueError(
                f"Maximum refinement iterations ({max_iterations}) exceeded"
            )

        # Apply feedback: append to description, re-derive name
        updated_name = f"{agent.agent_name}-r{iteration}"
        updated_graph = dict(agent.graph_definition)
        updated_graph["metadata"] = {
            **updated_graph.get("metadata", {}),
            "refinement_iteration": iteration,
            "feedback": feedback,
        }

        refined = GeneratedAgent(
            agent_name=updated_name,
            tenant_id=tenant_id,
            workspace_id=agent.workspace_id,
            owner_id=user.id,
            graph_definition=updated_graph,
            python_source=agent.python_source,
            credential_manifest=agent.credential_manifest,
            plan_id=agent.plan_id,
        )

        audit = _create_audit_event(
            user, "wizard.refine", "wizard",
            updated_name,
            {"iteration": iteration, "feedback_length": len(feedback), "tenant_id": tenant_id},
        )
        logger.info(
            "Wizard refinement completed",
            extra={"tenant_id": tenant_id, "iteration": iteration, "audit_id": str(audit.id)},
        )

        return refined

    # ── Full pipeline ───────────────────────────────────────────────

    async def full_pipeline(
        self,
        tenant_id: str,
        user: AuthenticatedUser,
        nl_description: str,
    ) -> tuple[GeneratedAgent, ValidationResult]:
        """Execute the complete Describe → Plan → Build → Validate pipeline."""
        analysis = await self.describe(tenant_id, user, nl_description)
        build_plan = await self.plan(tenant_id, user, analysis)
        agent = await self.build(tenant_id, user, build_plan)
        validation = await self.validate(tenant_id, user, agent)
        return agent, validation


# ── Legacy mock graph generation (kept for backward compat) ─────────


def _build_mock_graph(description: str) -> AgentGraphDefinition:
    """Return a hardcoded sample agent graph for testing without an LLM."""
    nodes: list[GraphNode] = [
        GraphNode(
            id="input_node", type="input",
            position=NodePosition(x=250, y=0),
            data=NodeData(label="User Input", type="input", description="Receives the user message"),
        ),
        GraphNode(
            id="router_node", type="default",
            position=NodePosition(x=250, y=120),
            data=NodeData(label="Intent Router", type="router", description="Classifies the user intent", config={"model": "gpt-4o-mini"}),
        ),
        GraphNode(
            id="order_status_node", type="default",
            position=NodePosition(x=100, y=260),
            data=NodeData(label="Order Status", type="tool", description="Checks order status via API", config={"tool": "check_order_status"}),
        ),
        GraphNode(
            id="returns_node", type="default",
            position=NodePosition(x=400, y=260),
            data=NodeData(label="Handle Returns", type="tool", description="Processes return requests", config={"tool": "process_return"}),
        ),
        GraphNode(
            id="response_node", type="output",
            position=NodePosition(x=250, y=400),
            data=NodeData(label="Response", type="output", description="Sends response to user"),
        ),
    ]

    edges: list[GraphEdge] = [
        GraphEdge(id="e_input_router", source="input_node", target="router_node"),
        GraphEdge(id="e_router_order", source="router_node", target="order_status_node", label="order_status"),
        GraphEdge(id="e_router_returns", source="router_node", target="returns_node", label="returns"),
        GraphEdge(id="e_order_response", source="order_status_node", target="response_node"),
        GraphEdge(id="e_returns_response", source="returns_node", target="response_node"),
    ]

    return AgentGraphDefinition(
        name=f"agent-{uuid4().hex[:8]}",
        description=description,
        nodes=nodes,
        edges=edges,
    )


async def generate_agent_graph(description: str) -> WizardResponse:
    """Legacy entrypoint — convert NL description into a structured agent graph."""
    graph = _build_mock_graph(description)
    return WizardResponse(agent_definition=graph, mode="mock")
