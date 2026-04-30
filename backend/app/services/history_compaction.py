"""History compaction service — W12 (Continue-as-New).

Implements continue-as-new, which creates a new WorkflowRun linked to an
existing run via a RunChain row. Long-running workflows can roll over without
accumulating unbounded event history.

Public surface:
  - continue_as_new(session, *, run_id, new_input, reason) -> WorkflowRun
        Create a new run linked to the old one via RunChain.
  - get_run_chain(session, *, run_id) -> list[dict]
        Return the full chain for the given run (by chain_id lookup).

ADR-008 §6 governs the RunChain schema. WorkflowRun does NOT gain
chain_id / parent_run_id columns — join through RunChain.run_id.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.run_chain import RunChain
from app.models.workflow import WorkflowRun
from app.services.execution_facade import ExecutionFacade

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.utcnow()


async def continue_as_new(
    session: AsyncSession,
    *,
    run_id: UUID,
    new_input: dict[str, Any] | None = None,
    reason: str,
) -> WorkflowRun:
    """Create a new run linked to an existing run via RunChain.

    Steps:
    1. Load the parent run; validate it exists and is not already in a chain
       that cannot continue (handled by uniqueness constraint).
    2. Determine chain_id, root_run_id, and generation_number:
       - If the parent is already a chain member, inherit chain_id and root_run_id,
         increment generation_number.
       - Otherwise, create a new chain rooted at the parent.
    3. Compact state from the parent run (output_data + definition_snapshot summary).
    4. Create the new run via ExecutionFacade.create_run.
    5. Write the RunChain row for the new run.
    6. Write the RunChain row for the root run if this is the first continue-as-new.

    Returns the newly created WorkflowRun.

    Raises ValueError if the parent run does not exist or if the new run
    cannot be created.
    """
    parent = await session.get(WorkflowRun, run_id)
    if parent is None:
        raise ValueError(f"run {run_id} not found")

    # Check if parent already belongs to a chain.
    parent_chain_entry = await _find_chain_entry_for_run(session, run_id)

    if parent_chain_entry is not None:
        chain_id = parent_chain_entry.chain_id
        root_run_id = parent_chain_entry.root_run_id
        generation_number = parent_chain_entry.generation_number + 1
    else:
        # First continue-as-new from this run — create a new chain.
        chain_id = uuid4()
        root_run_id = run_id
        generation_number = 1

        # Create the root entry (generation=0) for the parent run.
        root_entry = RunChain(
            chain_id=chain_id,
            root_run_id=root_run_id,
            parent_run_id=root_run_id,  # self-referential for root
            run_id=root_run_id,
            generation_number=0,
            compacted_state=None,
            continue_reason="chain_root",
        )
        session.add(root_entry)
        await session.flush()

    # Compact the parent's state to carry forward.
    compacted_state: dict[str, Any] = {
        "parent_run_id": str(run_id),
        "parent_status": parent.status,
        "parent_output": parent.output_data,
        "generation": generation_number,
    }

    # Create the child run via ExecutionFacade (preserves XOR contract +
    # hash-chained events).
    child_run, _ = await ExecutionFacade.create_run(
        session,
        kind=parent.kind or "workflow",
        workflow_id=parent.workflow_id,
        agent_id=parent.agent_id,
        tenant_id=parent.tenant_id,
        input_data=new_input if new_input is not None else (parent.input_data or {}),
        triggered_by=f"continue_as_new:{run_id}",
        trigger_type="continue_as_new",
    )

    # Write the RunChain row for the child run.
    child_entry = RunChain(
        chain_id=chain_id,
        root_run_id=root_run_id,
        parent_run_id=run_id,
        run_id=child_run.id,
        generation_number=generation_number,
        compacted_state=compacted_state,
        continue_reason=reason,
    )
    session.add(child_entry)
    await session.flush()
    await session.commit()
    await session.refresh(child_run)

    log.info(
        "history_compaction.continue_as_new: chain=%s gen=%d parent=%s child=%s",
        chain_id,
        generation_number,
        run_id,
        child_run.id,
    )
    return child_run


async def get_run_chain(
    session: AsyncSession,
    *,
    run_id: UUID | None = None,
    chain_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """Return the full chain as an ordered list of dicts.

    Pass either run_id (looks up chain_id from the chain table) or chain_id
    directly. Results are ordered by generation_number ascending.

    Returns an empty list if the run is not part of any chain.
    """
    if chain_id is None:
        if run_id is None:
            raise ValueError("one of run_id or chain_id must be provided")
        entry = await _find_chain_entry_for_run(session, run_id)
        if entry is None:
            return []
        chain_id = entry.chain_id

    stmt = (
        select(RunChain)
        .where(RunChain.chain_id == chain_id)
        .order_by(RunChain.generation_number.asc())
    )
    result = await session.exec(stmt)
    entries = list(result.all())

    return [
        {
            "chain_id": str(e.chain_id),
            "run_id": str(e.run_id),
            "parent_run_id": str(e.parent_run_id),
            "root_run_id": str(e.root_run_id),
            "generation_number": e.generation_number,
            "continue_reason": e.continue_reason,
            "compacted_state": e.compacted_state,
            "created_at": e.created_at.isoformat(),
        }
        for e in entries
    ]


# ── Internal helpers ──────────────────────────────────────────────────


async def _find_chain_entry_for_run(
    session: AsyncSession,
    run_id: UUID,
) -> RunChain | None:
    """Return the RunChain row for a given run_id, or None."""
    stmt = (
        select(RunChain)
        .where(RunChain.run_id == run_id)
        .limit(1)
    )
    result = await session.exec(stmt)
    return result.first()


__all__ = [
    "continue_as_new",
    "get_run_chain",
]
