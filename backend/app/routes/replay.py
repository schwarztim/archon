"""Replay routes — W10.

Endpoints for event-log replay and hash-chain verification.

POST /api/v1/runs/{run_id}/replay         — trigger replay verification
GET  /api/v1/runs/{run_id}/replay/state   — get reconstructed state
GET  /api/v1/runs/{run_id}/replay/verify  — verify hash chain
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.database import get_session as get_async_session
from app.services import replay_service

router = APIRouter(prefix="/runs", tags=["replay"])


@router.post("/{run_id}/replay", summary="Trigger replay verification")
async def trigger_replay(
    run_id: UUID,
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    """Run a full replay + chain verification and return the result."""
    try:
        result = await replay_service.compare_replay(session, run_id=run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result


@router.get("/{run_id}/replay/state", summary="Get reconstructed state")
async def get_replay_state(
    run_id: UUID,
    target_sequence: int | None = None,
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    """Reconstruct run state from the event log.

    Optionally pass ``target_sequence`` to replay up to a specific event.
    """
    try:
        if target_sequence is not None:
            state = await replay_service.replay_to_event(
                session, run_id=run_id, target_sequence=target_sequence
            )
        else:
            state = await replay_service.reconstruct_state(
                session, run_id=run_id
            )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return state


@router.get("/{run_id}/replay/verify", summary="Verify hash chain")
async def verify_chain(
    run_id: UUID,
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    """Verify the hash-chain integrity for all events on a run.

    Returns ``{"valid": true}`` when the chain is intact;
    ``{"valid": false}`` when tampering is detected.
    """
    try:
        valid = await replay_service.verify_event_chain(
            session, run_id=run_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"run_id": str(run_id), "valid": valid}
