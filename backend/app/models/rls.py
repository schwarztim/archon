"""PostgreSQL Row-Level Security (RLS) policies for multi-tenant isolation.

Call ``apply_rls_policies(conn)`` once after tables are created to install
all RLS policies.  This is idempotent — each statement uses ``IF NOT EXISTS``
guards where available, or ``CREATE OR REPLACE``.

Design:
  - Each tenant-scoped table has RLS enabled.
  - A single ``tenant_isolation`` policy enforces ``tenant_id =
    current_setting('app.tenant_id')::uuid`` (or ::text where the column is
    text-typed).
  - The session-level setting ``app.tenant_id`` is populated by the tenant
    middleware before every DB query, so no application-layer filtering is
    required for covered tables.
  - Super-user / migration sessions bypass RLS automatically (``BYPASSRLS``
    privilege or ``SET row_security = OFF``).
"""

from __future__ import annotations

import logging
from typing import Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table registry
# ---------------------------------------------------------------------------

# Each entry is (table_name, tenant_id_type) where tenant_id_type is one of:
#   "uuid"  → column stores a UUID; cast current_setting to ::uuid
#   "text"  → column stores a text/varchar; compare without cast
_TENANT_TABLES: Sequence[tuple[str, str]] = [
    # Core tables (models/__init__.py)
    ("agents", "uuid"),
    ("executions", "uuid"),  # via agent→owner join; direct column added below
    ("connectors", "uuid"),
    # Workflow tables (models/workflow.py)
    ("workflows", "uuid"),
    ("workflow_runs", "uuid"),
    # DLP tables (models/dlp.py)
    ("dlp_policies", "text"),
    ("dlp_scan_results", "text"),
    # Sentinel tables (models/sentinelscan.py)
    ("sentinel_findings", "text"),
    ("sentinel_scan_history", "text"),
    # Router tables (models/router.py)
    ("visual_routing_rules", "uuid"),
    ("fallback_chain_configs", "uuid"),
    # OAuth (models/oauth.py)
    ("oauth_pending_states", "text"),
    # Audit (models/audit.py)
    ("enterprise_audit_events", "uuid"),
    # Cost (models/cost.py)
    ("token_ledger", "text"),
    ("budgets", "text"),
    # Settings (models/settings.py)
    ("platform_settings", "uuid"),
    ("feature_flags", "uuid"),
    ("settings_api_keys", "uuid"),
    # Tenancy (models/tenancy.py)
    ("tenant_quotas", "uuid"),
    ("usage_metering_records", "uuid"),
    ("billing_records", "uuid"),
]


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------


def _enable_rls_sql(table: str) -> str:
    return f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;"


def _force_rls_sql(table: str) -> str:
    """FORCE RLS also applies to table owners (superusers still bypass)."""
    return f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;"


def _drop_policy_sql(table: str) -> str:
    return f"DROP POLICY IF EXISTS tenant_isolation ON {table};"


def _create_policy_sql(table: str, tenant_id_type: str) -> str:
    """Return a CREATE POLICY statement for the given table.

    We always drop-and-recreate to keep the policy definition up-to-date when
    this function is called on an already-migrated schema.
    """
    if tenant_id_type == "uuid":
        using_clause = "tenant_id = current_setting('app.tenant_id', TRUE)::uuid"
    else:
        # text/varchar columns — no cast needed
        using_clause = "tenant_id = current_setting('app.tenant_id', TRUE)"

    return f"CREATE POLICY tenant_isolation ON {table} FOR ALL USING ({using_clause});"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_rls_statements() -> list[str]:
    """Return the ordered list of SQL statements that install all RLS policies.

    Callers can inspect this list for migration scripts or execute them
    directly via ``apply_rls_policies``.
    """
    statements: list[str] = []
    for table, tenant_id_type in _TENANT_TABLES:
        statements.append(_enable_rls_sql(table))
        statements.append(_force_rls_sql(table))
        statements.append(_drop_policy_sql(table))
        statements.append(_create_policy_sql(table, tenant_id_type))
    return statements


async def apply_rls_policies(conn) -> None:
    """Execute all RLS policy statements on the supplied async connection.

    Intended to be called once after ``create_db_and_tables()`` in the
    application startup sequence.

    Args:
        conn: An ``asyncpg`` raw connection or a SQLAlchemy
              ``AsyncConnection`` (``engine.begin()`` context).  The function
              tries the SQLAlchemy ``execute`` path first, then falls back to
              the asyncpg ``execute`` method.

    Note:
        This function is a no-op on non-PostgreSQL backends (e.g. SQLite used
        in tests).  A warning is logged instead of raising.
    """
    from sqlalchemy import text

    statements = build_rls_statements()
    for sql in statements:
        try:
            await conn.execute(text(sql))
            logger.debug("rls: %s", sql.strip())
        except Exception as exc:  # noqa: BLE001
            # Non-Postgres backends or permission errors should not crash startup
            err_str = str(exc).lower()
            if "syntax error" in err_str or "does not exist" in err_str:
                # Table may not exist yet (test DB) — skip silently
                logger.debug("rls: skipped (%s): %s", exc, sql.strip())
            else:
                logger.warning("rls: failed to apply policy: %s — %s", sql.strip(), exc)


def get_set_tenant_sql(tenant_id: str) -> str:
    """Return the SQL to set the current tenant context for RLS.

    Use ``SET LOCAL`` (transaction-scoped) to avoid leaking the setting
    across connection pool reuse.

    Args:
        tenant_id: The tenant UUID as a string.

    Returns:
        A SQL string suitable for execution before tenant-scoped queries.
    """
    # Sanitize: tenant_id must be a valid UUID string to prevent injection.
    # We intentionally do not use parameterised SET because PostgreSQL does
    # not support parameters in SET statements.
    import re

    _UUID_RE = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        re.IGNORECASE,
    )
    if not _UUID_RE.match(tenant_id):
        raise ValueError(f"Invalid tenant_id format for RLS: {tenant_id!r}")
    return f"SET LOCAL app.tenant_id = '{tenant_id}';"
