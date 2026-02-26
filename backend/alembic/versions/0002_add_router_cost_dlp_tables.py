"""add_router_cost_dlp_tables

Revision ID: 0002_add_router_cost_dlp_tables
Revises: 0001_initial
Create Date: 2026-02-25

Creates all enterprise feature tables:
- model_providers + provider_health_history (router/model management)
- routing_rules, visual_routing_rules, fallback_chain_configs, model_registry (router)
- token_ledger, provider_pricing, budgets, cost_alerts, department_budgets (cost engine)
- dlp_policies, dlp_scan_results, dlp_detected_entities (DLP)
- sentinelscan tables: discovery scans, discovered services, risk classifications,
  findings, scan history (SentinelScan)
- connector_health_history (connectors)
- Various other enterprise tables imported from all model files

Also:
- Adds tenant_id to agents and executions tables
- Creates tenant_id indexes on all new tables
- Enables RLS with tenant isolation policies
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_add_router_cost_dlp_tables"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enable_rls(table: str, tenant_col: str = "tenant_id") -> None:
    """Enable RLS and create tenant isolation policy for a table."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
        USING ({tenant_col}::text = current_setting('app.tenant_id', true))
    """)


def upgrade() -> None:
    # ── 1. model_providers ─────────────────────────────────────────────
    op.create_table(
        "model_providers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("vault_path", sa.Text(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("health_status", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("supported_models", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("rate_limit_rpm", sa.Integer(), nullable=True),
        sa.Column("rate_limit_tpm", sa.Integer(), nullable=True),
        sa.Column("custom_headers", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_model_providers_tenant_id",
        "model_providers",
        ["tenant_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_model_providers_name",
        "model_providers",
        ["name"],
        unique=False,
        if_not_exists=True,
    )
    _enable_rls("model_providers")

    # ── 2. provider_health_history ──────────────────────────────────────
    op.create_table(
        "provider_health_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "provider_id",
            sa.Uuid(),
            sa.ForeignKey("model_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("error_rate_pct", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("requests_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Text(), nullable=False, server_default="healthy"),
        sa.Column(
            "recorded_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_provider_health_history_provider_id",
        "provider_health_history",
        ["provider_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_provider_health_history_tenant_id",
        "provider_health_history",
        ["tenant_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_provider_health_history_recorded_at",
        "provider_health_history",
        ["recorded_at"],
        unique=False,
        if_not_exists=True,
    )
    _enable_rls("provider_health_history")

    # ── 3. model_registry ──────────────────────────────────────────────
    op.create_table(
        "model_registry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "context_window", sa.Integer(), nullable=False, server_default="4096"
        ),
        sa.Column(
            "supports_streaming", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "cost_per_input_token", sa.Float(), nullable=False, server_default="0.0"
        ),
        sa.Column(
            "cost_per_output_token", sa.Float(), nullable=False, server_default="0.0"
        ),
        sa.Column("speed_tier", sa.Text(), nullable=False, server_default="medium"),
        sa.Column("avg_latency_ms", sa.Float(), nullable=False, server_default="500.0"),
        sa.Column(
            "data_classification", sa.Text(), nullable=False, server_default="general"
        ),
        sa.Column("is_on_prem", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("health_status", sa.Text(), nullable=False, server_default="healthy"),
        sa.Column("error_rate", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("vault_secret_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_model_registry_name",
        "model_registry",
        ["name"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_model_registry_provider",
        "model_registry",
        ["provider"],
        unique=False,
        if_not_exists=True,
    )

    # ── 4. routing_rules ───────────────────────────────────────────────
    op.create_table(
        "routing_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("strategy", sa.Text(), nullable=False, server_default="balanced"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("weight_cost", sa.Float(), nullable=False, server_default="0.25"),
        sa.Column("weight_latency", sa.Float(), nullable=False, server_default="0.25"),
        sa.Column(
            "weight_capability", sa.Float(), nullable=False, server_default="0.25"
        ),
        sa.Column(
            "weight_sensitivity", sa.Float(), nullable=False, server_default="0.25"
        ),
        sa.Column("conditions", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("fallback_chain", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_routing_rules_name",
        "routing_rules",
        ["name"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_routing_rules_department_id",
        "routing_rules",
        ["department_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_routing_rules_agent_id",
        "routing_rules",
        ["agent_id"],
        unique=False,
        if_not_exists=True,
    )

    # ── 5. visual_routing_rules ────────────────────────────────────────
    op.create_table(
        "visual_routing_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("action", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_visual_routing_rules_tenant_id",
        "visual_routing_rules",
        ["tenant_id"],
        unique=False,
        if_not_exists=True,
    )

    # ── 6. fallback_chain_configs ──────────────────────────────────────
    op.create_table(
        "fallback_chain_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("chain", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_fallback_chain_configs_tenant_id",
        "fallback_chain_configs",
        ["tenant_id"],
        unique=False,
        if_not_exists=True,
    )

    # ── 7. provider_pricing ────────────────────────────────────────────
    op.create_table(
        "provider_pricing",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "cost_per_input_token", sa.Float(), nullable=False, server_default="0.0"
        ),
        sa.Column(
            "cost_per_output_token", sa.Float(), nullable=False, server_default="0.0"
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "effective_from",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("effective_to", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_provider_pricing_provider",
        "provider_pricing",
        ["provider"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_provider_pricing_model_id",
        "provider_pricing",
        ["model_id"],
        unique=False,
        if_not_exists=True,
    )

    # ── 8. token_ledger ────────────────────────────────────────────────
    op.create_table(
        "token_ledger",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column(
            "execution_id", sa.Uuid(), sa.ForeignKey("executions.id"), nullable=True
        ),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_cost", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("output_cost", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("total_cost", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("attribution_chain", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_token_ledger_tenant_id",
        "token_ledger",
        ["tenant_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_token_ledger_execution_id",
        "token_ledger",
        ["execution_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_token_ledger_agent_id",
        "token_ledger",
        ["agent_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_token_ledger_user_id",
        "token_ledger",
        ["user_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_token_ledger_department_id",
        "token_ledger",
        ["department_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_token_ledger_workspace_id",
        "token_ledger",
        ["workspace_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_token_ledger_provider",
        "token_ledger",
        ["provider"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_token_ledger_model_id",
        "token_ledger",
        ["model_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_token_ledger_created_at",
        "token_ledger",
        ["created_at"],
        unique=False,
        if_not_exists=True,
    )
    _enable_rls("token_ledger")

    # ── 9. budgets ─────────────────────────────────────────────────────
    op.create_table(
        "budgets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False, server_default="department"),
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("limit_amount", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("spent_amount", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("currency", sa.Text(), nullable=False, server_default="USD"),
        sa.Column("period", sa.Text(), nullable=False, server_default="monthly"),
        sa.Column(
            "period_start", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("period_end", sa.DateTime(), nullable=True),
        sa.Column("enforcement", sa.Text(), nullable=False, server_default="soft"),
        sa.Column("hard_limit", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "alert_threshold_pct", sa.Float(), nullable=False, server_default="80.0"
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "alert_thresholds",
            sa.JSON(),
            nullable=False,
            server_default="[50.0, 75.0, 90.0, 100.0]",
        ),
        sa.Column(
            "rollover_enabled", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_budgets_tenant_id",
        "budgets",
        ["tenant_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_budgets_name", "budgets", ["name"], unique=False, if_not_exists=True
    )
    op.create_index(
        "ix_budgets_department_id",
        "budgets",
        ["department_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_budgets_workspace_id",
        "budgets",
        ["workspace_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_budgets_user_id", "budgets", ["user_id"], unique=False, if_not_exists=True
    )
    op.create_index(
        "ix_budgets_agent_id", "budgets", ["agent_id"], unique=False, if_not_exists=True
    )
    _enable_rls("budgets")

    # ── 10. cost_alerts ────────────────────────────────────────────────
    op.create_table(
        "cost_alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("budget_id", sa.Uuid(), sa.ForeignKey("budgets.id"), nullable=False),
        sa.Column("alert_type", sa.Text(), nullable=False, server_default="threshold"),
        sa.Column("severity", sa.Text(), nullable=False, server_default="warning"),
        sa.Column("threshold_pct", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("current_spend", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("budget_limit", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "is_acknowledged", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column(
            "acknowledged_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_cost_alerts_budget_id",
        "cost_alerts",
        ["budget_id"],
        unique=False,
        if_not_exists=True,
    )

    # ── 11. department_budgets ─────────────────────────────────────────
    op.create_table(
        "department_budgets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column(
            "budget_usd",
            sa.Numeric(10, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("period", sa.Text(), nullable=False, server_default="monthly"),
        sa.Column(
            "warn_threshold_pct", sa.Integer(), nullable=False, server_default="80"
        ),
        sa.Column(
            "block_threshold_pct", sa.Integer(), nullable=False, server_default="100"
        ),
        sa.Column(
            "current_spend_usd",
            sa.Numeric(10, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "period_start", sa.Date(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "period_end", sa.Date(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_department_budgets_tenant_id",
        "department_budgets",
        ["tenant_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_department_budgets_department_id",
        "department_budgets",
        ["department_id"],
        unique=False,
        if_not_exists=True,
    )
    _enable_rls("department_budgets")

    # ── 12. dlp_policies ──────────────────────────────────────────────
    op.create_table(
        "dlp_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("description_nl", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("detector_types", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("custom_patterns", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("rules", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("action", sa.Text(), nullable=False, server_default="redact"),
        sa.Column("sensitivity", sa.Text(), nullable=False, server_default="high"),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_dlp_policies_tenant_id",
        "dlp_policies",
        ["tenant_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_dlp_policies_name",
        "dlp_policies",
        ["name"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_dlp_policies_agent_id",
        "dlp_policies",
        ["agent_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_dlp_policies_department_id",
        "dlp_policies",
        ["department_id"],
        unique=False,
        if_not_exists=True,
    )
    _enable_rls("dlp_policies")

    # ── 13. dlp_scan_results ───────────────────────────────────────────
    op.create_table(
        "dlp_scan_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("policy_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("text_hash", sa.Text(), nullable=True),
        sa.Column("has_findings", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("findings_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("action_taken", sa.Text(), nullable=False, server_default="none"),
        sa.Column("entity_types_found", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_dlp_scan_results_tenant_id",
        "dlp_scan_results",
        ["tenant_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_dlp_scan_results_policy_id",
        "dlp_scan_results",
        ["policy_id"],
        unique=False,
        if_not_exists=True,
    )
    _enable_rls("dlp_scan_results")

    # ── 14. dlp_detected_entities ──────────────────────────────────────
    op.create_table(
        "dlp_detected_entities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "scan_result_id",
            sa.Uuid(),
            sa.ForeignKey("dlp_scan_results.id"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("start_offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("end_offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("redacted_value", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_dlp_detected_entities_scan_result_id",
        "dlp_detected_entities",
        ["scan_result_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_dlp_detected_entities_entity_type",
        "dlp_detected_entities",
        ["entity_type"],
        unique=False,
        if_not_exists=True,
    )

    # ── 15. sentinelscan_discovery_scans ───────────────────────────────
    op.create_table(
        "sentinelscan_discovery_scans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("scan_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("results_summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("services_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("initiated_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_sentinelscan_discovery_scans_name",
        "sentinelscan_discovery_scans",
        ["name"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_sentinelscan_discovery_scans_scan_type",
        "sentinelscan_discovery_scans",
        ["scan_type"],
        unique=False,
        if_not_exists=True,
    )

    # ── 16. sentinelscan_discovered_services ───────────────────────────
    op.create_table(
        "sentinelscan_discovered_services",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "scan_id",
            sa.Uuid(),
            sa.ForeignKey("sentinelscan_discovery_scans.id"),
            nullable=False,
        ),
        sa.Column("service_name", sa.Text(), nullable=False),
        sa.Column("service_type", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("detection_source", sa.Text(), nullable=False),
        sa.Column("department", sa.Text(), nullable=True),
        sa.Column("owner", sa.Text(), nullable=True),
        sa.Column("user_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "data_sensitivity", sa.Text(), nullable=False, server_default="unknown"
        ),
        sa.Column(
            "is_sanctioned", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "first_seen", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "last_seen", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_sentinelscan_discovered_services_scan_id",
        "sentinelscan_discovered_services",
        ["scan_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_sentinelscan_discovered_services_service_name",
        "sentinelscan_discovered_services",
        ["service_name"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_sentinelscan_discovered_services_service_type",
        "sentinelscan_discovered_services",
        ["service_type"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_sentinelscan_discovered_services_provider",
        "sentinelscan_discovered_services",
        ["provider"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_sentinelscan_discovered_services_department",
        "sentinelscan_discovered_services",
        ["department"],
        unique=False,
        if_not_exists=True,
    )

    # ── 17. sentinelscan_risk_classifications ──────────────────────────
    op.create_table(
        "sentinelscan_risk_classifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "service_id",
            sa.Uuid(),
            sa.ForeignKey("sentinelscan_discovered_services.id"),
            nullable=False,
        ),
        sa.Column("risk_tier", sa.Text(), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("factors", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "data_sensitivity_score", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "blast_radius_score", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("compliance_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "model_capability_score", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("policy_violations", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "recommended_actions", sa.JSON(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "classified_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_sentinelscan_risk_classifications_service_id",
        "sentinelscan_risk_classifications",
        ["service_id"],
        unique=True,
        if_not_exists=True,
    )
    op.create_index(
        "ix_sentinelscan_risk_classifications_risk_tier",
        "sentinelscan_risk_classifications",
        ["risk_tier"],
        unique=False,
        if_not_exists=True,
    )

    # ── 18. sentinel_findings ──────────────────────────────────────────
    op.create_table(
        "sentinel_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("scan_id", sa.Text(), nullable=False),
        sa.Column("service_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("service_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("finding_type", sa.Text(), nullable=False, server_default=""),
        sa.Column("severity", sa.Text(), nullable=False, server_default="low"),
        sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("remediated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_sentinel_findings_tenant_id",
        "sentinel_findings",
        ["tenant_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_sentinel_findings_scan_id",
        "sentinel_findings",
        ["scan_id"],
        unique=False,
        if_not_exists=True,
    )
    _enable_rls("sentinel_findings")

    # ── 19. sentinel_scan_history ──────────────────────────────────────
    op.create_table(
        "sentinel_scan_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("scan_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="completed"),
        sa.Column("services_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("findings_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scan_data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_sentinel_scan_history_tenant_id",
        "sentinel_scan_history",
        ["tenant_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_sentinel_scan_history_scan_id",
        "sentinel_scan_history",
        ["scan_id"],
        unique=True,
        if_not_exists=True,
    )
    _enable_rls("sentinel_scan_history")

    # ── 20. connector_health_history ───────────────────────────────────
    op.create_table(
        "connector_health_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="healthy"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_connector_health_history_tenant_id",
        "connector_health_history",
        ["tenant_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_connector_health_history_connector_id",
        "connector_health_history",
        ["connector_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_connector_health_history_timestamp",
        "connector_health_history",
        ["timestamp"],
        unique=False,
        if_not_exists=True,
    )
    _enable_rls("connector_health_history")

    # ── 21. Add tenant_id to agents ────────────────────────────────────
    # Use a try/except-style approach: check column existence via SQL
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='agents' AND column_name='tenant_id'
            ) THEN
                ALTER TABLE agents ADD COLUMN tenant_id TEXT;
                UPDATE agents SET tenant_id = 'default-tenant' WHERE tenant_id IS NULL;
                ALTER TABLE agents ALTER COLUMN tenant_id SET NOT NULL;
                CREATE INDEX IF NOT EXISTS ix_agents_tenant_id ON agents (tenant_id);
                ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
                ALTER TABLE agents FORCE ROW LEVEL SECURITY;
                CREATE POLICY tenant_isolation ON agents
                    USING (tenant_id = current_setting('app.tenant_id', true));
            END IF;
        END $$;
    """)

    # ── 22. Add tenant_id to executions ───────────────────────────────
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='executions' AND column_name='tenant_id'
            ) THEN
                ALTER TABLE executions ADD COLUMN tenant_id TEXT;
                UPDATE executions SET tenant_id = 'default-tenant' WHERE tenant_id IS NULL;
                ALTER TABLE executions ALTER COLUMN tenant_id SET NOT NULL;
                CREATE INDEX IF NOT EXISTS ix_executions_tenant_id ON executions (tenant_id);
                ALTER TABLE executions ENABLE ROW LEVEL SECURITY;
                ALTER TABLE executions FORCE ROW LEVEL SECURITY;
                CREATE POLICY tenant_isolation ON executions
                    USING (tenant_id = current_setting('app.tenant_id', true));
            END IF;
        END $$;
    """)


def downgrade() -> None:
    # Remove tenant_id from agents/executions (best-effort)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='executions' AND column_name='tenant_id'
            ) THEN
                DROP POLICY IF EXISTS tenant_isolation ON executions;
                ALTER TABLE executions DISABLE ROW LEVEL SECURITY;
                DROP INDEX IF EXISTS ix_executions_tenant_id;
                ALTER TABLE executions DROP COLUMN IF EXISTS tenant_id;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='agents' AND column_name='tenant_id'
            ) THEN
                DROP POLICY IF EXISTS tenant_isolation ON agents;
                ALTER TABLE agents DISABLE ROW LEVEL SECURITY;
                DROP INDEX IF EXISTS ix_agents_tenant_id;
                ALTER TABLE agents DROP COLUMN IF EXISTS tenant_id;
            END IF;
        END $$;
    """)

    # Drop tables in reverse dependency order
    op.drop_table("connector_health_history", if_exists=True)
    op.drop_table("sentinel_scan_history", if_exists=True)
    op.drop_table("sentinel_findings", if_exists=True)
    op.drop_table("sentinelscan_risk_classifications", if_exists=True)
    op.drop_table("sentinelscan_discovered_services", if_exists=True)
    op.drop_table("sentinelscan_discovery_scans", if_exists=True)
    op.drop_table("dlp_detected_entities", if_exists=True)
    op.drop_table("dlp_scan_results", if_exists=True)
    op.drop_table("dlp_policies", if_exists=True)
    op.drop_table("department_budgets", if_exists=True)
    op.drop_table("cost_alerts", if_exists=True)
    op.drop_table("budgets", if_exists=True)
    op.drop_table("token_ledger", if_exists=True)
    op.drop_table("provider_pricing", if_exists=True)
    op.drop_table("fallback_chain_configs", if_exists=True)
    op.drop_table("visual_routing_rules", if_exists=True)
    op.drop_table("routing_rules", if_exists=True)
    op.drop_table("model_registry", if_exists=True)
    op.drop_table("provider_health_history", if_exists=True)
    op.drop_table("model_providers", if_exists=True)
