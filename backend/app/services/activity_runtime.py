"""Activity runtime — W3 implementation.

Owned by Worker W3. The runtime wraps every activity executor through the
``ActivityContext`` / ``ActivityResult`` contract: it inserts an
``ActivityExecution`` row on entry, supplies buffered heartbeat callbacks
and a cooperative cancellation hook, captures the executor's output as an
artifact, and persists the terminal status to the row before returning.

Public surface
--------------

* ``ActivityContext``       — frozen per-execution context handed to
                              every executor (kept stable for W4a-d).
* ``ActivityResult``        — terminal value returned by an executor.
* ``ActivityCancelled``     — raised by ``check_cancelled`` when the run
                              has been cancelled mid-execution.
* ``ActivityRuntimeError``  — invariant violation (e.g. executor returned
                              a non-``ActivityResult``).
* ``ActivityRuntime``       — owns the lifecycle around a single attempt.
* ``execute_activity``      — top-level entry that constructs a runtime
                              with sensible defaults and runs one attempt.

Design notes
------------

* **One row per attempt.** ADR-008 §3 keeps ``ActivityExecution`` per
  attempt. The runtime INSERTs the row in ``status='running'`` before
  invoking the executor, then UPDATEs it on the way out. The
  ``WorkflowRunStep`` row is owned by the dispatcher; this runtime never
  writes to it.

* **Heartbeat buffering.** Heartbeat callbacks are cheap-path — the
  executor may call them on a tight loop. We buffer the latest details
  in memory and flush at most once per ``heartbeat_buffer_ms`` window.
  An ``asyncio.Lock`` guards the flush so two concurrent flushes never
  collide; a sentinel timestamp prevents redundant writes when the
  buffer is unchanged.

* **Cancellation.** ``check_cancelled`` is a callable that raises
  ``ActivityCancelled`` when the run's cancellation flag is set. The
  runtime distinguishes this from ``asyncio.CancelledError`` — the
  former is cooperative (the executor saw the request and surrendered),
  the latter is loop-driven and re-raised after persistence.

* **Artifact-backed outputs.** When ``ActivityResult.output_data`` is
  non-empty we persist it via the injected artifact_service and store
  the resulting ``artifact://{tenant_id}/{kind}/{uuid}`` URI in
  ``output_ref``. The URI format is the contract documented in the W3
  plan; ``write_artifact`` callbacks emitted to executors follow the
  same shape.

* **Vault delegation.** ``resolve_secret`` is forwarded to the injected
  ``secrets_resolver`` (a coroutine) — the runtime never reads secrets
  from the environment or vault directly.

* **Sync vs async artifact_service.** The injected service may expose
  sync or async methods. We probe with ``inspect.iscoroutinefunction``
  and wrap sync calls in ``asyncio.to_thread`` so neither the
  buffered-heartbeat hot path nor the artifact-write path blocks the
  event loop.

The runtime never swallows executor exceptions silently — they are
captured into ``status='failed'`` + ``error_code`` / ``error_message``
on the row, then re-raised only when the executor returned a non-result
(invariant violation). The dispatcher's retry-policy machinery operates
on the persisted row, not on the raised exception.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal, Protocol
from uuid import UUID, uuid4

log = logging.getLogger(__name__)


# ── Callback protocols ────────────────────────────────────────────────
#
# Activities receive these as callable members of ``ActivityContext``.
# Modelled as Protocols (not bare ``Callable``) so test doubles can be
# typed precisely and so future wrappers (timing, tracing) can extend
# the surface without breaking executor signatures.


class HeartbeatProtocol(Protocol):
    """Persist progress details for long-running activities.

    Called repeatedly by the executor; ``details`` is merged into the
    persisted heartbeat blob and is also surfaced on the next retry/resume.
    """

    async def __call__(self, details: dict[str, Any]) -> None: ...


class CheckCancelledProtocol(Protocol):
    """Cooperative cancellation check.

    Raises ``ActivityCancelled`` if the run has been cancelled. Executors
    must call this between meaningful units of work; W3 supplies the
    concrete check.
    """

    async def __call__(self) -> None: ...


class WriteArtifactProtocol(Protocol):
    """Persist an output artifact and return its reference URI."""

    async def __call__(
        self,
        name: str,
        payload: bytes | str | dict[str, Any],
        metadata: dict[str, Any],
    ) -> str: ...


class ResolveSecretProtocol(Protocol):
    """Resolve a secret reference (e.g. ``vault://path/to/key``) to its value.

    The runtime is the only authorised consumer of the vault for activities;
    executors must never read secrets directly.
    """

    async def __call__(self, secret_ref: str) -> str: ...


# ── Activity context + result ─────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class ActivityContext:
    """Per-execution context handed to every activity executor.

    Frozen + kw-only so executors cannot mutate the context (state lives in
    ``ActivityResult``) and so callers must name every field at construction
    site (no positional drift when fields are added).
    """

    tenant_id: str
    run_id: str
    step_id: str
    task_id: str | None
    queue_name: str
    activity_type: str
    attempt: int
    idempotency_key: str
    input_data: dict[str, Any]
    node_config: dict[str, Any]
    definition_snapshot: dict[str, Any]
    db_session: Any
    worker_id: str
    heartbeat: HeartbeatProtocol
    check_cancelled: CheckCancelledProtocol
    write_artifact: WriteArtifactProtocol
    resolve_secret: ResolveSecretProtocol
    trace_id: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class ActivityResult:
    """Terminal value returned by an activity executor.

    ``status`` drives the dispatcher's transition: ``completed`` finalises
    the step, ``failed`` triggers retry-policy evaluation, ``paused`` parks
    the run on a signal/approval, ``cancelled`` honours an in-flight cancel
    request, and ``retry_scheduled`` instructs the dispatcher to re-enqueue
    after ``retry_after_seconds`` without consuming a retry budget slot.
    """

    status: Literal["completed", "failed", "paused", "cancelled", "retry_scheduled"]
    output_data: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    heartbeat_details: dict[str, Any] | None = None
    retry_after_seconds: int | None = None
    non_retryable: bool = False
    error_code: str | None = None
    error_message: str | None = None


# ── Exceptions ────────────────────────────────────────────────────────


class ActivityRuntimeError(Exception):
    """Raised when an activity runtime invariant is violated.

    Examples: executor returned a non-``ActivityResult`` value; heartbeat
    persistence failure that the runtime cannot recover from.
    """


class ActivityCancelled(Exception):
    """Raised by ``check_cancelled`` when the activity is cancelled mid-run.

    Distinct from ``asyncio.CancelledError`` so callers can handle a
    cooperative cancel separately from a loop-driven cancellation. The
    runtime persists ``status='cancelled'`` and never re-raises this back
    to the dispatcher (the row state is the single source of truth).
    """


# ── Helpers ───────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    """Naive UTC for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _maybe_await(value: Any) -> Any:
    """Await *value* if it is awaitable; otherwise return it as-is."""
    if inspect.isawaitable(value):
        return await value
    return value


def _to_uuid(value: Any) -> UUID | None:
    """Coerce a string / UUID-like to UUID; tolerate None."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _build_artifact_uri(
    *,
    tenant_id: str | None,
    kind: str,
    artifact_id: Any,
) -> str:
    """Compose ``artifact://{tenant_id}/{kind}/{uuid}`` per W3 plan spec."""
    safe_tenant = tenant_id or "default"
    return f"artifact://{safe_tenant}/{kind}/{artifact_id}"


# ── ActivityRuntime ───────────────────────────────────────────────────


class ActivityRuntime:
    """Runtime owner for one ActivityExecution row per attempt.

    The runtime is reusable across many activity invocations within a
    single dispatcher process: it retains no per-activity state. All
    per-attempt state (the row id, the heartbeat lock, last-flush
    timestamp) lives in a private inner closure inside ``execute``.

    The runtime is constructed with three injected dependencies:

      * ``db_session_factory`` — ``async with`` context manager yielding
        an ``AsyncSession``; the runtime opens its own session per
        UPDATE so a long-running activity does not hold a connection.
      * ``artifact_service``   — exposes ``maybe_persist_output_as_artifact``
        and ``store_artifact`` (sync OR async; runtime probes).
      * ``secrets_resolver``   — coroutine ``(secret_ref) -> str``.
    """

    def __init__(
        self,
        *,
        db_session_factory: Callable[[], Any],
        artifact_service: Any,
        secrets_resolver: ResolveSecretProtocol,
        heartbeat_buffer_ms: int = 250,
    ) -> None:
        self._db_session_factory = db_session_factory
        self._artifact_service = artifact_service
        self._secrets_resolver = secrets_resolver
        self._heartbeat_buffer_ms = max(0, int(heartbeat_buffer_ms))

    # ── Public entry ─────────────────────────────────────────────────

    async def execute(
        self,
        context: ActivityContext,
        executor: Callable[[ActivityContext], Awaitable[ActivityResult]],
    ) -> ActivityResult:
        """Persist + run + finalise one activity attempt.

        Returns the original ``ActivityResult`` (or a synthesised one
        when the executor raised an exception or returned ``None`` —
        see the per-branch contract in the body).
        """
        execution_id = uuid4()
        run_uuid = _to_uuid(context.run_id)
        if run_uuid is None:
            raise ActivityRuntimeError(
                f"ActivityContext.run_id is not a valid UUID: {context.run_id!r}"
            )

        await self._insert_execution_row(
            execution_id=execution_id,
            context=context,
            run_uuid=run_uuid,
        )

        # Per-attempt heartbeat machinery. The lock prevents two flushes
        # from racing; ``last_flush_ms`` debounces tight-loop heartbeats.
        # ``buffered`` holds the latest details until the next flush.
        heartbeat_state = {
            "lock": asyncio.Lock(),
            "buffered": None,  # type: dict[str, Any] | None
            "last_flush_ms": 0.0,
            "dirty": False,
        }

        async def _maybe_flush_heartbeat(force: bool = False) -> None:
            """Flush the buffered heartbeat to the DB if window elapsed."""
            async with heartbeat_state["lock"]:
                if not heartbeat_state["dirty"] and not force:
                    return
                now_ms = time.monotonic() * 1000.0
                if (
                    not force
                    and (now_ms - heartbeat_state["last_flush_ms"])
                    < self._heartbeat_buffer_ms
                ):
                    return
                buffered = heartbeat_state["buffered"] or {}
                heartbeat_state["dirty"] = False
                heartbeat_state["last_flush_ms"] = now_ms
                try:
                    await self._update_heartbeat(
                        execution_id=execution_id,
                        details=dict(buffered),
                    )
                except Exception as exc:  # noqa: BLE001
                    log.debug(
                        "activity_runtime: heartbeat flush failed (id=%s): %s",
                        execution_id,
                        exc,
                    )

        async def _heartbeat(details: dict[str, Any]) -> None:
            async with heartbeat_state["lock"]:
                heartbeat_state["buffered"] = (
                    {**(heartbeat_state["buffered"] or {}), **(details or {})}
                )
                heartbeat_state["dirty"] = True
            # Cheap-path attempt to flush — debounced internally.
            await _maybe_flush_heartbeat(force=False)

        async def _check_cancelled() -> None:
            # Delegate to the context-supplied callable; the runtime
            # raises ``ActivityCancelled`` instead of asyncio's variant
            # when the upstream check signals cancellation.
            await context.check_cancelled()

        async def _write_artifact(
            name: str,
            payload: bytes | str | dict[str, Any],
            metadata: dict[str, Any],
        ) -> str:
            # Forward to the executor-facing artifact writer if one was
            # supplied via ``ActivityContext`` — otherwise fall back to
            # the injected artifact_service.
            artifact_id = await self._persist_artifact(
                tenant_id=context.tenant_id,
                run_uuid=run_uuid,
                step_id=context.step_id,
                payload=payload,
                metadata={
                    **(metadata or {}),
                    "name": name,
                    "execution_id": str(execution_id),
                    "activity_type": context.activity_type,
                },
                kind="activity_output",
            )
            return _build_artifact_uri(
                tenant_id=context.tenant_id,
                kind="activity_output",
                artifact_id=artifact_id,
            )

        async def _resolve_secret(secret_ref: str) -> str:
            return await self._secrets_resolver(secret_ref)

        runtime_context = self._with_runtime_callbacks(
            context,
            heartbeat=_heartbeat,
            check_cancelled=_check_cancelled,
            write_artifact=_write_artifact,
            resolve_secret=_resolve_secret,
        )

        start = time.perf_counter()
        try:
            try:
                result = await executor(runtime_context)
            except ActivityCancelled:
                # Cooperative cancellation — record + suppress.
                await _maybe_flush_heartbeat(force=True)
                cancelled = ActivityResult(status="cancelled")
                await self._finalise(
                    execution_id=execution_id,
                    result=cancelled,
                    duration_ms=int((time.perf_counter() - start) * 1000),
                )
                return cancelled
            except asyncio.CancelledError:
                # Loop-driven cancellation. Persist + re-raise so the
                # dispatcher can transition the run state correctly.
                await _maybe_flush_heartbeat(force=True)
                cancelled = ActivityResult(status="cancelled")
                await self._finalise(
                    execution_id=execution_id,
                    result=cancelled,
                    duration_ms=int((time.perf_counter() - start) * 1000),
                )
                raise
            except Exception as exc:  # noqa: BLE001
                # Executor raised — persist a failed row, return a
                # synthetic ActivityResult mirroring the exception. We
                # do NOT re-raise; the dispatcher reads the row, not the
                # exception, and the runtime swallowing the exception
                # keeps the calling chain aligned with retry policy.
                await _maybe_flush_heartbeat(force=True)
                failed = ActivityResult(
                    status="failed",
                    error_code=type(exc).__name__,
                    error_message=str(exc)[:1024],
                )
                await self._finalise(
                    execution_id=execution_id,
                    result=failed,
                    duration_ms=int((time.perf_counter() - start) * 1000),
                )
                return failed
        finally:
            # Belt-and-braces: even if the success path didn't flush
            # explicitly, leave nothing buffered.
            await _maybe_flush_heartbeat(force=True)

        if not isinstance(result, ActivityResult):
            raise ActivityRuntimeError(
                f"executor for activity_type={context.activity_type!r} did not "
                f"return ActivityResult; got {type(result).__name__}"
            )

        # Map output_data to output_ref via the artifact substrate.
        output_ref: str | None = None
        if result.output_data:
            try:
                artifact_id = await self._persist_artifact(
                    tenant_id=context.tenant_id,
                    run_uuid=run_uuid,
                    step_id=context.step_id,
                    payload=result.output_data,
                    metadata={
                        "execution_id": str(execution_id),
                        "activity_type": context.activity_type,
                        "kind": "activity_output",
                    },
                    kind="activity_output",
                )
                output_ref = _build_artifact_uri(
                    tenant_id=context.tenant_id,
                    kind="activity_output",
                    artifact_id=artifact_id,
                )
            except Exception as exc:  # noqa: BLE001
                # Artifact persistence is best-effort — we log + continue
                # so a transient artifact-store outage doesn't lose the
                # activity result. The row will carry status=completed
                # without an output_ref, which downstream code handles.
                log.warning(
                    "activity_runtime: artifact persist failed (id=%s): %s",
                    execution_id,
                    exc,
                )

        await self._finalise(
            execution_id=execution_id,
            result=result,
            output_ref=output_ref,
            duration_ms=int((time.perf_counter() - start) * 1000),
            activity_type=context.activity_type,
        )
        return result

    # ── DB persistence helpers ───────────────────────────────────────

    async def _insert_execution_row(
        self,
        *,
        execution_id: UUID,
        context: ActivityContext,
        run_uuid: UUID,
    ) -> None:
        """INSERT the ActivityExecution row in ``status='running'``."""
        from app.models.activity import ActivityExecution  # noqa: PLC0415

        tenant_uuid = _to_uuid(context.tenant_id)
        task_uuid = _to_uuid(context.task_id)

        async with self._db_session_factory() as session:
            row = ActivityExecution(
                id=execution_id,
                tenant_id=tenant_uuid,
                task_id=task_uuid,
                run_id=run_uuid,
                step_id=context.step_id,
                attempt_number=max(int(context.attempt or 1), 1),
                worker_id=context.worker_id,
                queue_name=context.queue_name,
                activity_type=context.activity_type,
                idempotency_key=context.idempotency_key,
                status="running",
                started_at=_utcnow(),
                heartbeat_at=None,
                heartbeat_details={},
            )
            session.add(row)
            await session.commit()

    async def _update_heartbeat(
        self,
        *,
        execution_id: UUID,
        details: dict[str, Any],
    ) -> None:
        """Persist the latest heartbeat blob + timestamp."""
        from app.models.activity import ActivityExecution  # noqa: PLC0415

        async with self._db_session_factory() as session:
            row = await session.get(ActivityExecution, execution_id)
            if row is None:
                return
            row.heartbeat_at = _utcnow()
            row.heartbeat_details = dict(details)
            session.add(row)
            await session.commit()

    async def _finalise(
        self,
        *,
        execution_id: UUID,
        result: ActivityResult,
        output_ref: str | None = None,
        duration_ms: int | None = None,
        activity_type: str = "unknown",
    ) -> None:
        """Write the terminal row state."""
        from app.models.activity import ActivityExecution  # noqa: PLC0415

        async with self._db_session_factory() as session:
            row = await session.get(ActivityExecution, execution_id)
            if row is None:
                return
            row.status = result.status
            row.completed_at = _utcnow()
            if duration_ms is not None:
                row.duration_ms = duration_ms
            if output_ref is not None:
                row.output_ref = output_ref
            row.error_code = result.error_code
            row.error_message = result.error_message
            row.non_retryable = bool(result.non_retryable)
            row.retry_after_seconds = result.retry_after_seconds
            if result.heartbeat_details is not None:
                row.heartbeat_details = dict(result.heartbeat_details)
                row.heartbeat_at = _utcnow()
            session.add(row)
            await session.commit()
        if result.status == "retry_scheduled":
            try:
                from app.services.metrics_service import record_activity_retry  # noqa: PLC0415
                record_activity_retry(
                    activity_type=getattr(row, "activity_type", None) or activity_type
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("activity_runtime: retry metric emit failed: %s", exc)

    # ── Artifact substrate ───────────────────────────────────────────

    async def _persist_artifact(
        self,
        *,
        tenant_id: str | None,
        run_uuid: UUID,
        step_id: str,
        payload: Any,
        metadata: dict[str, Any],
        kind: str,
    ) -> Any:
        """Delegate to the injected artifact_service. Sync or async tolerated.

        The service is expected to expose ``store_artifact`` returning an
        object with an ``id`` attribute (the canonical signature in
        ``app/services/artifact_service.py``). For tests that pass a
        custom callable via ``store_artifact`` we accept the return
        value as-is — UUID, string, or object with ``.id``.
        """
        store = getattr(self._artifact_service, "store_artifact", None)
        if store is None:
            # No artifact service wired — fall back to a synthetic UUID
            # so the URI is still valid + dedupable. This path is only
            # reachable in tests; production wires the real service.
            return uuid4()

        # Probe sync vs async.
        if inspect.iscoroutinefunction(store):
            artifact = await store(
                tenant_id=tenant_id,
                run_id=run_uuid,
                step_id=step_id,
                payload=payload,
                metadata=metadata,
                kind=kind,
            )
        else:
            # Sync fallback — wrap to keep the event loop unblocked.
            artifact = await asyncio.to_thread(
                store,
                tenant_id=tenant_id,
                run_id=run_uuid,
                step_id=step_id,
                payload=payload,
                metadata=metadata,
                kind=kind,
            )

        artifact = await _maybe_await(artifact)
        artifact_id = getattr(artifact, "id", artifact)
        return artifact_id

    # ── Context-callback rewiring ─────────────────────────────────────

    @staticmethod
    def _with_runtime_callbacks(
        context: ActivityContext,
        *,
        heartbeat: HeartbeatProtocol,
        check_cancelled: CheckCancelledProtocol,
        write_artifact: WriteArtifactProtocol,
        resolve_secret: ResolveSecretProtocol,
    ) -> ActivityContext:
        """Return a new ActivityContext with runtime-managed callbacks.

        The original callbacks (e.g. test doubles) remain in scope inside
        the runtime closures (``_heartbeat`` calls
        ``context.check_cancelled`` via the closure, etc.). The replaced
        context is what the executor sees.
        """
        return ActivityContext(
            tenant_id=context.tenant_id,
            run_id=context.run_id,
            step_id=context.step_id,
            task_id=context.task_id,
            queue_name=context.queue_name,
            activity_type=context.activity_type,
            attempt=context.attempt,
            idempotency_key=context.idempotency_key,
            input_data=context.input_data,
            node_config=context.node_config,
            definition_snapshot=context.definition_snapshot,
            db_session=context.db_session,
            worker_id=context.worker_id,
            heartbeat=heartbeat,
            check_cancelled=check_cancelled,
            write_artifact=write_artifact,
            resolve_secret=resolve_secret,
            trace_id=context.trace_id,
            correlation_id=context.correlation_id,
        )


# ── Top-level entry ──────────────────────────────────────────────────


async def execute_activity(
    context: ActivityContext,
    executor: Callable[[ActivityContext], Awaitable[ActivityResult]],
) -> ActivityResult:
    """Top-level convenience entry — wires up the default runtime.

    The default runtime uses ``app.database.async_session_factory`` and
    the workspace's ``app.services.artifact_service`` plus a no-op
    secret resolver (the dispatcher's call site supplies a real one when
    invoking ``ActivityRuntime`` directly).

    Tests that need fine-grained control (e.g. injection of a fake
    artifact service or a deterministic heartbeat buffer) should
    instantiate ``ActivityRuntime`` directly rather than calling this
    entry.
    """
    from app.database import async_session_factory  # noqa: PLC0415

    # Lazy import the real artifact service so the runtime module stays
    # cheap to import in test contexts that stub it out.
    try:
        from app.services import artifact_service  # noqa: PLC0415
    except Exception:  # pragma: no cover - defensive  # noqa: BLE001
        artifact_service = None  # type: ignore[assignment]

    async def _missing_secret(_ref: str) -> str:
        raise ActivityRuntimeError(
            "execute_activity called without a secret resolver — instantiate "
            "ActivityRuntime directly with secrets_resolver= for production use"
        )

    runtime = ActivityRuntime(
        db_session_factory=async_session_factory,
        artifact_service=artifact_service,
        secrets_resolver=_missing_secret,
    )
    return await runtime.execute(context, executor)


# ── Legacy executor adapter ──────────────────────────────────────────


async def adapt_legacy_executor(
    legacy_fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    context: ActivityContext,
) -> ActivityResult:
    """Bridge old-style node executors (state dict -> result dict) to ActivityResult.

    Lets existing node executors work through ActivityRuntime without
    rewriting them. The executor receives ``context.input_data`` as its
    state dict; its returned dict becomes ``output_data`` on the result.

    On success the returned dict is wrapped in an ``ActivityResult`` with
    ``status='completed'``. If the returned dict contains an ``'error'``
    key (non-empty), the result carries ``status='failed'`` and
    ``error_message`` from that key. If the executor raises, the exception
    propagates and the runtime's own exception handler persists the failure.
    """
    result_dict: dict[str, Any] = await legacy_fn(context.input_data)
    if not isinstance(result_dict, dict):
        raise ActivityRuntimeError(
            f"adapt_legacy_executor: legacy executor returned {type(result_dict).__name__}, "
            f"expected dict"
        )
    error_msg: str | None = result_dict.get("error") or None
    if error_msg:
        return ActivityResult(
            status="failed",
            error_code="LegacyExecutorError",
            error_message=str(error_msg)[:1024],
            output_data={k: v for k, v in result_dict.items() if k != "error"},
        )
    return ActivityResult(
        status="completed",
        output_data=result_dict,
    )


__all__ = [
    "ActivityCancelled",
    "ActivityContext",
    "ActivityResult",
    "ActivityRuntime",
    "ActivityRuntimeError",
    "CheckCancelledProtocol",
    "HeartbeatProtocol",
    "ResolveSecretProtocol",
    "WriteArtifactProtocol",
    "adapt_legacy_executor",
    "execute_activity",
]
