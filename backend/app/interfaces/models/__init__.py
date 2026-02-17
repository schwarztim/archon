"""Shared type stubs used by Archon interface contracts."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class ExecutionStatus(str, Enum):
    """Execution lifecycle states (mirrors API contract)."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class AgentDefinition:
    """Minimal agent representation for interface type-checking."""
    id: str
    name: str
    definition: dict[str, Any]
    status: str = "draft"
    owner_id: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)

@dataclass
class ExecutionResult:
    """Result returned by the execution engine."""
    execution_id: str
    agent_id: str
    status: ExecutionStatus
    output: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    duration_ms: int | None = None

@dataclass
class UserClaims:
    """Decoded JWT claims for an authenticated user."""
    user_id: str
    email: str
    roles: list[str] = field(default_factory=list)

@dataclass
class User:
    """Minimal user representation for auth checks."""
    id: str
    email: str
    roles: list[str] = field(default_factory=list)

@dataclass
class Event:
    """An event published on the event bus."""
    type: str
    payload: dict[str, Any]
    channel: str = ""
    timestamp: str = ""

__all__ = [
    "AgentDefinition", "Event", "ExecutionResult",
    "ExecutionStatus", "User", "UserClaims",
]