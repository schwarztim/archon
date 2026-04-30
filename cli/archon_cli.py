#!/usr/bin/env python3
"""Archon CLI — scriptable interface to the Archon orchestration platform.

Uses only public REST APIs (httpx). Never imports from backend/.

Configuration
-------------
ARCHON_API_URL  Base URL for the API (default: http://localhost:8000/api/v1)
ARCHON_TOKEN    Bearer token for authentication

Usage
-----
  archon run start --workflow-id UUID [--input JSON]
  archon run list [--status STATUS] [--queue QUEUE]
  archon run get RUN_ID
  archon run cancel RUN_ID --reason TEXT
  archon run terminate RUN_ID --reason TEXT
  archon run pause RUN_ID
  archon run resume RUN_ID
  archon run signal RUN_ID --name NAME --payload JSON
  archon run query RUN_ID
  archon run events RUN_ID
  archon schedule list
  archon schedule create --workflow-id UUID --cron SPEC
  archon schedule backfill SCHEDULE_ID --start TIME --end TIME
  archon worker list
  archon queue list
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import click
import httpx

_DEFAULT_BASE_URL = "http://localhost:8000/api/v1"


def _get_client() -> httpx.Client:
    """Build an httpx Client with base URL and auth token from environment."""
    base_url = os.environ.get("ARCHON_API_URL", _DEFAULT_BASE_URL).rstrip("/")
    token = os.environ.get("ARCHON_TOKEN", "")
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=base_url, headers=headers, timeout=30.0)


def _print_json(data: Any) -> None:
    click.echo(json.dumps(data, indent=2, default=str))


def _handle_response(resp: httpx.Response) -> dict[str, Any]:
    """Raise a ClickException on non-2xx, otherwise return parsed JSON."""
    if resp.is_error:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise click.ClickException(
            f"API error {resp.status_code}: {json.dumps(detail, default=str)}"
        )
    return resp.json()


# ── Top-level group ────────────────────────────────────────────────────


@click.group()
def cli() -> None:
    """Archon CLI — scriptable orchestration platform client."""


# ── run group ─────────────────────────────────────────────────────────


@cli.group()
def run() -> None:
    """Workflow run commands."""


@run.command("start")
@click.option("--workflow-id", required=True, help="Workflow UUID to execute")
@click.option(
    "--input",
    "input_json",
    default="{}",
    help="JSON input data for the run",
)
def run_start(workflow_id: str, input_json: str) -> None:
    """Start a new workflow run."""
    try:
        input_data = json.loads(input_json)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Invalid JSON for --input: {exc}") from exc

    with _get_client() as client:
        resp = client.post(
            "/workflows/run",
            json={"workflow_id": workflow_id, "input_data": input_data},
        )
        _print_json(_handle_response(resp))


@run.command("list")
@click.option("--status", default=None, help="Filter by status")
@click.option("--queue", default=None, help="Filter by queue name")
@click.option("--limit", default=50, help="Maximum number of results")
@click.option("--offset", default=0, help="Pagination offset")
def run_list(status: str | None, queue: str | None, limit: int, offset: int) -> None:
    """List workflow runs with optional filters."""
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status:
        params["status"] = status
    if queue:
        params["queue"] = queue

    with _get_client() as client:
        resp = client.get("/runs", params=params)
        _print_json(_handle_response(resp))


@run.command("get")
@click.argument("run_id")
def run_get(run_id: str) -> None:
    """Get details for a specific run including its event log."""
    with _get_client() as client:
        resp = client.get(f"/runs/{run_id}")
        _print_json(_handle_response(resp))


@run.command("cancel")
@click.argument("run_id")
@click.option("--reason", required=True, help="Reason for cancellation")
def run_cancel(run_id: str, reason: str) -> None:
    """Request cooperative cancellation of a run."""
    with _get_client() as client:
        resp = client.post(f"/runs/{run_id}/cancel", json={"reason": reason})
        _print_json(_handle_response(resp))


@run.command("terminate")
@click.argument("run_id")
@click.option("--reason", required=True, help="Reason for termination")
def run_terminate(run_id: str, reason: str) -> None:
    """Hard-stop a run immediately."""
    with _get_client() as client:
        resp = client.post(f"/runs/{run_id}/terminate", json={"reason": reason})
        _print_json(_handle_response(resp))


@run.command("pause")
@click.argument("run_id")
@click.option("--reason", default="operator_pause", help="Reason for pausing")
def run_pause(run_id: str, reason: str) -> None:
    """Suspend a running or queued run."""
    with _get_client() as client:
        resp = client.post(f"/runs/{run_id}/pause", json={"reason": reason})
        _print_json(_handle_response(resp))


@run.command("resume")
@click.argument("run_id")
@click.option("--reason", default="operator_resume", help="Reason for resuming")
def run_resume(run_id: str, reason: str) -> None:
    """Resume a paused run."""
    with _get_client() as client:
        resp = client.post(f"/runs/{run_id}/resume", json={"reason": reason})
        _print_json(_handle_response(resp))


@run.command("signal")
@click.argument("run_id")
@click.option("--name", required=True, help="Signal name")
@click.option(
    "--payload",
    "payload_json",
    default="{}",
    help="JSON signal payload",
)
def run_signal(run_id: str, name: str, payload_json: str) -> None:
    """Send a named signal to a running workflow."""
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Invalid JSON for --payload: {exc}") from exc

    with _get_client() as client:
        resp = client.post(
            f"/runs/{run_id}/signal",
            json={"signal_name": name, "payload": payload},
        )
        _print_json(_handle_response(resp))


@run.command("query")
@click.argument("run_id")
def run_query(run_id: str) -> None:
    """Query the current state of a workflow run."""
    with _get_client() as client:
        resp = client.get(f"/runs/{run_id}/query")
        _print_json(_handle_response(resp))


@run.command("events")
@click.argument("run_id")
@click.option("--cursor", default=0, help="Event sequence cursor (for pagination)")
@click.option("--limit", default=50, help="Maximum number of events per page")
def run_events(run_id: str, cursor: int, limit: int) -> None:
    """Stream paginated events for a run (W13 timeline endpoint)."""
    with _get_client() as client:
        resp = client.get(
            f"/runs/{run_id}/timeline",
            params={"cursor": cursor, "limit": limit},
        )
        _print_json(_handle_response(resp))


# ── schedule group ────────────────────────────────────────────────────


@cli.group()
def schedule() -> None:
    """Schedule management commands."""


@schedule.command("list")
@click.option("--limit", default=50, help="Maximum number of results")
@click.option("--offset", default=0, help="Pagination offset")
def schedule_list(limit: int, offset: int) -> None:
    """List all schedules."""
    with _get_client() as client:
        resp = client.get("/schedules", params={"limit": limit, "offset": offset})
        _print_json(_handle_response(resp))


@schedule.command("create")
@click.option("--workflow-id", required=True, help="Workflow UUID to schedule")
@click.option("--cron", required=True, help="Cron expression (e.g. '0 * * * *')")
@click.option("--timezone", default="UTC", help="Timezone for cron evaluation")
@click.option(
    "--overlap-policy",
    default="skip",
    type=click.Choice(
        ["skip", "buffer_one", "buffer_all", "cancel_running", "terminate_running", "allow_all"]
    ),
    help="Overlap policy",
)
def schedule_create(
    workflow_id: str, cron: str, timezone: str, overlap_policy: str
) -> None:
    """Create a new cron schedule for a workflow."""
    with _get_client() as client:
        resp = client.post(
            "/schedules",
            json={
                "workflow_id": workflow_id,
                "calendar_spec": cron,
                "spec_kind": "cron",
                "timezone": timezone,
                "overlap_policy": overlap_policy,
            },
        )
        _print_json(_handle_response(resp))


@schedule.command("backfill")
@click.argument("schedule_id")
@click.option("--start", required=True, help="Backfill start time (ISO-8601 UTC)")
@click.option("--end", required=True, help="Backfill end time (ISO-8601 UTC)")
def schedule_backfill(schedule_id: str, start: str, end: str) -> None:
    """Trigger backfill for missed schedule firings in a time window."""
    with _get_client() as client:
        resp = client.post(
            f"/schedules/{schedule_id}/backfill",
            json={"start": start, "end": end},
        )
        _print_json(_handle_response(resp))


# ── worker group ──────────────────────────────────────────────────────


@cli.group()
def worker() -> None:
    """Worker management commands."""


@worker.command("list")
@click.option("--limit", default=50, help="Maximum number of results")
@click.option("--offset", default=0, help="Pagination offset")
def worker_list(limit: int, offset: int) -> None:
    """List registered workers."""
    with _get_client() as client:
        resp = client.get("/workers", params={"limit": limit, "offset": offset})
        _print_json(_handle_response(resp))


# ── queue group ───────────────────────────────────────────────────────


@cli.group()
def queue() -> None:
    """Task queue management commands."""


@queue.command("list")
@click.option("--limit", default=50, help="Maximum number of results")
@click.option("--offset", default=0, help="Pagination offset")
def queue_list(limit: int, offset: int) -> None:
    """List task queues."""
    with _get_client() as client:
        resp = client.get("/task-queues", params={"limit": limit, "offset": offset})
        _print_json(_handle_response(resp))


if __name__ == "__main__":
    cli()
