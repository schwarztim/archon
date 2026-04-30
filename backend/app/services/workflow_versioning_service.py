"""Workflow definition versioning service — W11.

Manages WorkflowDefinitionVersion rows per ADR-008 §5.

Public surface:
  - snapshot_definition(session, *, workflow_id) -> WorkflowDefinitionVersion
        Create a new version from the current workflow definition.
  - get_version(session, *, workflow_id, version) -> WorkflowDefinitionVersion
        Retrieve a specific version by version_number.
  - list_versions(session, *, workflow_id) -> list[WorkflowDefinitionVersion]
        Return all versions for a workflow, ordered by version_number asc.
  - check_compatibility(session, *, worker_version, ...) -> bool
        Check whether a worker_version tag is in the version's compatibility_set.
  - deprecate_version(session, *, workflow_id, version) -> None
        Soft-deprecate a version (sets deprecated_at).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.workflow import Workflow
from app.models.workflow_version import WorkflowDefinitionVersion

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.utcnow()


async def snapshot_definition(
    session: AsyncSession,
    *,
    workflow_id: UUID,
    changelog: str = "",
    created_by: str = "",
    compatibility_set: list[str] | None = None,
) -> WorkflowDefinitionVersion:
    """Create a new WorkflowDefinitionVersion from the current workflow state.

    version_number is the next monotonic integer after the current maximum
    for this workflow_id (starting at 1 when no prior versions exist).

    Raises ValueError if the workflow does not exist.
    """
    workflow = await session.get(Workflow, workflow_id)
    if workflow is None:
        raise ValueError(f"workflow {workflow_id} not found")

    existing = await list_versions(session, workflow_id=workflow_id)
    if existing:
        next_version = max(v.version_number for v in existing) + 1
    else:
        next_version = 1

    schema_snapshot: dict[str, Any] = {
        "steps": list(workflow.steps or []),
        "graph_definition": workflow.graph_definition,
        "name": workflow.name,
        "description": workflow.description,
        "captured_at": datetime.utcnow().isoformat(),
    }

    version = WorkflowDefinitionVersion(
        workflow_id=workflow_id,
        tenant_id=workflow.tenant_id,
        version_number=next_version,
        schema_snapshot=schema_snapshot,
        compatibility_set=list(compatibility_set or []),
        changelog=changelog,
        created_by=created_by,
    )
    session.add(version)
    await session.flush()
    await session.commit()
    await session.refresh(version)
    return version


async def get_version(
    session: AsyncSession,
    *,
    workflow_id: UUID,
    version: int,
) -> WorkflowDefinitionVersion:
    """Retrieve a specific WorkflowDefinitionVersion by version_number.

    Raises ValueError if not found.
    """
    stmt = (
        select(WorkflowDefinitionVersion)
        .where(WorkflowDefinitionVersion.workflow_id == workflow_id)
        .where(WorkflowDefinitionVersion.version_number == version)
        .limit(1)
    )
    result = await session.exec(stmt)
    row = result.first()
    if row is None:
        raise ValueError(
            f"version {version} not found for workflow {workflow_id}"
        )
    return row


async def list_versions(
    session: AsyncSession,
    *,
    workflow_id: UUID,
) -> list[WorkflowDefinitionVersion]:
    """Return all WorkflowDefinitionVersion rows for a workflow.

    Results are ordered by version_number ascending.
    """
    stmt = (
        select(WorkflowDefinitionVersion)
        .where(WorkflowDefinitionVersion.workflow_id == workflow_id)
        .order_by(WorkflowDefinitionVersion.version_number.asc())
    )
    result = await session.exec(stmt)
    return list(result.all())


async def check_compatibility(
    session: AsyncSession,
    *,
    worker_version: str,
    definition_version: WorkflowDefinitionVersion | None = None,
    definition_version_id: UUID | None = None,
) -> bool:
    """Check whether a worker_version tag is compatible with a definition version.

    An empty compatibility_set means "any worker version is compatible".

    Pass either a WorkflowDefinitionVersion instance or a definition_version_id.
    Raises ValueError if definition_version_id is provided but not found.
    """
    if definition_version is None:
        if definition_version_id is None:
            raise ValueError(
                "one of definition_version or definition_version_id must be provided"
            )
        row = await session.get(WorkflowDefinitionVersion, definition_version_id)
        if row is None:
            raise ValueError(
                f"WorkflowDefinitionVersion {definition_version_id} not found"
            )
        definition_version = row

    compat = definition_version.compatibility_set or []
    if not compat:
        return True
    return worker_version in compat


async def deprecate_version(
    session: AsyncSession,
    *,
    workflow_id: UUID,
    version: int,
) -> None:
    """Soft-deprecate a WorkflowDefinitionVersion by setting deprecated_at.

    Idempotent: if already deprecated, the call is a no-op.
    Raises ValueError if not found.
    """
    row = await get_version(session, workflow_id=workflow_id, version=version)
    if row.deprecated_at is not None:
        return

    row.deprecated_at = _utcnow()
    session.add(row)
    await session.flush()
    await session.commit()


__all__ = [
    "check_compatibility",
    "deprecate_version",
    "get_version",
    "list_versions",
    "snapshot_definition",
]
