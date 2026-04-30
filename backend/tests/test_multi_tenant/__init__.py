"""Tests for the Archon multi-tenant manager service.

Phase 4 / WS12 — DB-level tenant isolation. The new modules cover:

* ``test_tenant_isolation`` — application-level filtering on SQLite +
  Postgres RLS policies (Postgres-only, skipped without
  ``ARCHON_TEST_POSTGRES_URL``).
* ``test_zero_uuid_rejection`` — strict-mode rejection of the legacy
  ``"default-tenant"`` / zero-UUID fallbacks.
* ``test_tenant_context_propagation`` — contextvar persistence across
  async boundaries and concurrent-task isolation.
"""
