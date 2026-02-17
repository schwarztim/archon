"""Archon background worker for async tasks.

Handles scheduled scans, secret rotation checks, and budget alerts.
Run via: python3 -m app.worker
"""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import datetime, timezone

from app.logging_config import get_logger, setup_logging

logger = get_logger(__name__)

_shutdown = asyncio.Event()


def _handle_signal(sig: signal.Signals) -> None:
    """Set shutdown event on SIGINT/SIGTERM."""
    logger.info("worker_signal_received", signal=sig.name)
    _shutdown.set()


async def _run_scheduled_scans() -> None:
    """Placeholder for scheduled security scans."""
    logger.debug("scheduled_scan_tick")


async def _run_rotation_checks() -> None:
    """Placeholder for secret rotation checks."""
    logger.debug("rotation_check_tick")


async def _run_budget_alerts() -> None:
    """Placeholder for budget alert evaluation."""
    logger.debug("budget_alert_tick")


async def main() -> None:
    """Run the worker event loop until shutdown signal."""
    setup_logging(log_level="INFO")
    logger.info("worker_started", time=datetime.now(tz=timezone.utc).isoformat())

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, sig)

    scan_interval = 300  # seconds

    while not _shutdown.is_set():
        try:
            await _run_scheduled_scans()
            await _run_rotation_checks()
            await _run_budget_alerts()
        except Exception:
            logger.exception("worker_tick_error")

        try:
            await asyncio.wait_for(_shutdown.wait(), timeout=scan_interval)
        except asyncio.TimeoutError:
            pass

    logger.info("worker_stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
