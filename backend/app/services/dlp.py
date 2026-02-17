"""DLP (Data Loss Prevention) engine for Archon.

Scans AI agent inputs/outputs for sensitive data using regex-based
pattern matching and classification rules.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.dlp import DLPDetectedEntity, DLPPolicy, DLPScanResult


# ── Built-in Detector Patterns ──────────────────────────────────────

# Patterns keyed by entity type with (regex, confidence) tuples.
# High-precision patterns get confidence 1.0; looser heuristics get lower.
BUILTIN_PATTERNS: dict[str, list[tuple[re.Pattern[str], float]]] = {
    "ssn": [
        (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), 1.0),
        (re.compile(r"\b\d{9}\b"), 0.5),  # bare 9-digit, lower confidence
    ],
    "credit_card": [
        # Visa
        (re.compile(r"\b4\d{3}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"), 1.0),
        # Mastercard
        (re.compile(r"\b5[1-5]\d{2}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"), 1.0),
        # Amex
        (re.compile(r"\b3[47]\d{2}[\s-]?\d{6}[\s-]?\d{5}\b"), 1.0),
        # Discover
        (re.compile(r"\b6(?:011|5\d{2})[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"), 1.0),
    ],
    "email": [
        (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), 0.95),
    ],
    "api_key": [
        # AWS access key
        (re.compile(r"\b(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b"), 1.0),
        # Generic long hex/base64 API key patterns (preceded by key-like label)
        (re.compile(
            r"(?i)(?:api[_-]?key|apikey|secret[_-]?key|access[_-]?token)"
            r"[\s:=]+['\"]?([A-Za-z0-9/+=_-]{20,})['\"]?"
        ), 0.85),
    ],
    "password": [
        (re.compile(
            r"(?i)(?:password|passwd|pwd)[\s:=]+['\"]?(\S{4,})['\"]?"
        ), 0.9),
    ],
}

# Redaction templates per entity type
_REDACT_MAP: dict[str, str] = {
    "ssn": "***-**-****",
    "credit_card": "****-****-****-****",
    "email": "[EMAIL REDACTED]",
    "api_key": "[API_KEY REDACTED]",
    "password": "[PASSWORD REDACTED]",
}


# ── Data Classes ────────────────────────────────────────────────────


class DetectionHit:
    """In-memory representation of a single detection hit."""

    __slots__ = ("entity_type", "start", "end", "matched_text", "confidence", "redacted")

    def __init__(
        self,
        entity_type: str,
        start: int,
        end: int,
        matched_text: str,
        confidence: float,
        redacted: str,
    ) -> None:
        self.entity_type = entity_type
        self.start = start
        self.end = end
        self.matched_text = matched_text
        self.confidence = confidence
        self.redacted = redacted

    def to_dict(self) -> dict[str, Any]:
        """Serialise hit (never includes raw matched_text)."""
        return {
            "entity_type": self.entity_type,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
            "redacted_value": self.redacted,
        }


# ── DLP Engine ──────────────────────────────────────────────────────


class DLPEngine:
    """Multi-pattern DLP scanner with policy management.

    Provides regex-based detection for SSN, credit cards, emails,
    API keys, and passwords.  Supports custom patterns via DLPPolicy.
    """

    # ── Scanning ────────────────────────────────────────────────────

    @staticmethod
    def scan_text(
        text: str,
        *,
        detector_types: list[str] | None = None,
        custom_patterns: dict[str, str] | None = None,
        min_confidence: float = 0.0,
    ) -> list[DetectionHit]:
        """Scan *text* for sensitive data and return detection hits.

        Args:
            text: The content to scan.
            detector_types: Subset of built-in detector names to use.
                If ``None``, all built-in detectors run.
            custom_patterns: Extra ``{name: regex}`` patterns to apply
                (confidence defaults to 0.8).
            min_confidence: Discard hits below this threshold.

        Returns:
            List of ``DetectionHit`` objects sorted by start offset.
        """
        hits: list[DetectionHit] = []

        # Built-in detectors
        active_types = detector_types or list(BUILTIN_PATTERNS.keys())
        for dtype in active_types:
            patterns = BUILTIN_PATTERNS.get(dtype, [])
            redact_tpl = _REDACT_MAP.get(dtype, "[REDACTED]")
            for pattern, confidence in patterns:
                if confidence < min_confidence:
                    continue
                for match in pattern.finditer(text):
                    hits.append(DetectionHit(
                        entity_type=dtype,
                        start=match.start(),
                        end=match.end(),
                        matched_text=match.group(),
                        confidence=confidence,
                        redacted=redact_tpl,
                    ))

        # Custom patterns
        if custom_patterns:
            for name, regex_str in custom_patterns.items():
                try:
                    compiled = re.compile(regex_str)
                except re.error:
                    continue  # skip invalid regex
                for match in compiled.finditer(text):
                    hits.append(DetectionHit(
                        entity_type=name,
                        start=match.start(),
                        end=match.end(),
                        matched_text=match.group(),
                        confidence=0.8,
                        redacted=f"[{name.upper()} REDACTED]",
                    ))

        # Deduplicate overlapping ranges: keep higher-confidence hit
        hits.sort(key=lambda h: (h.start, -h.confidence))
        deduped: list[DetectionHit] = []
        last_end = -1
        for hit in hits:
            if hit.start >= last_end:
                deduped.append(hit)
                last_end = hit.end
        return deduped

    @staticmethod
    def redact_text(
        text: str,
        *,
        detector_types: list[str] | None = None,
        custom_patterns: dict[str, str] | None = None,
        min_confidence: float = 0.0,
    ) -> tuple[str, list[DetectionHit]]:
        """Scan text and return a redacted copy alongside detection hits.

        Returns:
            ``(redacted_text, hits)`` tuple.
        """
        hits = DLPEngine.scan_text(
            text,
            detector_types=detector_types,
            custom_patterns=custom_patterns,
            min_confidence=min_confidence,
        )
        if not hits:
            return text, []

        # Build redacted string by replacing matched spans
        parts: list[str] = []
        cursor = 0
        for hit in hits:
            parts.append(text[cursor:hit.start])
            parts.append(hit.redacted)
            cursor = hit.end
        parts.append(text[cursor:])
        return "".join(parts), hits

    # ── Policy CRUD (async, DB-backed) ──────────────────────────────

    @staticmethod
    async def create_policy(session: AsyncSession, policy: DLPPolicy) -> DLPPolicy:
        """Persist a new DLP policy."""
        session.add(policy)
        await session.commit()
        await session.refresh(policy)
        return policy

    @staticmethod
    async def get_policy(session: AsyncSession, policy_id: UUID) -> DLPPolicy | None:
        """Return a DLP policy by ID."""
        return await session.get(DLPPolicy, policy_id)

    @staticmethod
    async def list_policies(
        session: AsyncSession,
        *,
        is_active: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[DLPPolicy], int]:
        """Return paginated DLP policies with optional filter and total count."""
        base = select(DLPPolicy)
        if is_active is not None:
            base = base.where(DLPPolicy.is_active == is_active)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(
            DLPPolicy.created_at.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        policies = list(result.all())
        return policies, total

    @staticmethod
    async def update_policy(
        session: AsyncSession,
        policy_id: UUID,
        data: dict[str, Any],
    ) -> DLPPolicy | None:
        """Partial-update a DLP policy. Returns None if not found."""
        policy = await session.get(DLPPolicy, policy_id)
        if policy is None:
            return None
        for key, value in data.items():
            if hasattr(policy, key):
                setattr(policy, key, value)
        session.add(policy)
        await session.commit()
        await session.refresh(policy)
        return policy

    @staticmethod
    async def delete_policy(session: AsyncSession, policy_id: UUID) -> bool:
        """Delete a DLP policy. Returns True if deleted."""
        policy = await session.get(DLPPolicy, policy_id)
        if policy is None:
            return False
        await session.delete(policy)
        await session.commit()
        return True

    # ── Scan & Persist ──────────────────────────────────────────────

    @staticmethod
    async def scan_and_record(
        session: AsyncSession,
        text: str,
        *,
        policy_id: UUID | None = None,
        source: str = "manual",
    ) -> DLPScanResult:
        """Run a scan and persist the result and detected entities to the DB.

        The raw text is **never** stored — only a SHA-256 hash.
        """
        # Resolve policy-specific detectors if a policy is provided
        detector_types: list[str] | None = None
        custom_patterns: dict[str, str] | None = None
        action = "none"
        if policy_id:
            policy = await session.get(DLPPolicy, policy_id)
            if policy and policy.is_active:
                detector_types = policy.detector_types or None
                custom_patterns = policy.custom_patterns or None
                action = policy.action

        hits = DLPEngine.scan_text(
            text,
            detector_types=detector_types,
            custom_patterns=custom_patterns,
        )

        text_hash = hashlib.sha256(text.encode()).hexdigest()
        entity_types_found = sorted({h.entity_type for h in hits})

        scan_result = DLPScanResult(
            policy_id=policy_id,
            source=source,
            text_hash=text_hash,
            has_findings=len(hits) > 0,
            findings_count=len(hits),
            action_taken=action if hits else "none",
            entity_types_found=entity_types_found,
        )
        session.add(scan_result)
        await session.flush()  # get scan_result.id

        for hit in hits:
            entity = DLPDetectedEntity(
                scan_result_id=scan_result.id,
                entity_type=hit.entity_type,
                confidence=hit.confidence,
                start_offset=hit.start,
                end_offset=hit.end,
                redacted_value=hit.redacted,
            )
            session.add(entity)

        await session.commit()
        await session.refresh(scan_result)
        return scan_result


__all__ = [
    "DLPEngine",
    "DetectionHit",
]
