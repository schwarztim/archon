"""Shared UTC datetime helper for naive TIMESTAMP columns."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return current UTC time as a naive datetime (no tzinfo).

    Use this for all TIMESTAMP WITHOUT TIME ZONE columns.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
