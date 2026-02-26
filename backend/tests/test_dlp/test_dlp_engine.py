"""Unit tests for DLPEngine — pattern detection, redaction, policy CRUD,
scan_and_record persistence, and min_confidence filtering.

All tests mock the async database session so no live DB is required.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.models.dlp import DLPPolicy, DLPScanResult
from app.services.dlp import DLPEngine, DetectionHit

# ── Fixed UUIDs ─────────────────────────────────────────────────────

POLICY_ID = UUID("dd000001-0001-0001-0001-000000000001")
SCAN_ID = UUID("55000001-0001-0001-0001-000000000001")
AGENT_ID = UUID("aa000001-0001-0001-0001-000000000001")
NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


# ── Factories ───────────────────────────────────────────────────────


def _mock_session() -> AsyncMock:
    """Create a mock AsyncSession with standard ORM method stubs."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


def _policy(
    *,
    pid: UUID = POLICY_ID,
    name: str = "Test Policy",
    is_active: bool = True,
    detector_types: list[str] | None = None,
    custom_patterns: dict[str, str] | None = None,
    action: str = "redact",
    sensitivity: str = "high",
) -> DLPPolicy:
    """Build a DLPPolicy with controllable fields."""
    return DLPPolicy(
        id=pid,
        name=name,
        is_active=is_active,
        detector_types=detector_types if detector_types is not None else ["ssn", "credit_card"],
        custom_patterns=custom_patterns if custom_patterns is not None else {},
        action=action,
        sensitivity=sensitivity,
        created_at=NOW,
        updated_at=NOW,
    )


def _scan_result(
    *,
    sid: UUID | None = None,
    policy_id: UUID | None = None,
    has_findings: bool = True,
    findings_count: int = 1,
    action_taken: str = "redact",
    entity_types_found: list[str] | None = None,
) -> DLPScanResult:
    """Build a DLPScanResult with controllable fields."""
    return DLPScanResult(
        id=sid or uuid4(),
        policy_id=policy_id,
        source="manual",
        text_hash="abc123",
        has_findings=has_findings,
        findings_count=findings_count,
        action_taken=action_taken,
        entity_types_found=entity_types_found or ["ssn"],
        created_at=NOW,
    )


def _exec_result(rows: list[Any]) -> MagicMock:
    """Create a mock result object whose .all() and .first() work."""
    result = MagicMock()
    result.all.return_value = rows
    result.first.return_value = rows[0] if rows else None
    return result


# ═══════════════════════════════════════════════════════════════════
# SSN Detection
# ═══════════════════════════════════════════════════════════════════


class TestSSNDetection:
    """Tests for SSN pattern detection."""

    def test_detects_formatted_ssn(self) -> None:
        """Detect standard formatted SSN (123-45-6789)."""
        hits = DLPEngine.scan_text("My SSN is 123-45-6789.")
        ssn_hits = [h for h in hits if h.entity_type == "ssn"]
        assert len(ssn_hits) == 1
        assert ssn_hits[0].confidence == 1.0
        assert ssn_hits[0].matched_text == "123-45-6789"

    def test_detects_bare_9digit_ssn_lower_confidence(self) -> None:
        """Bare 9-digit number detected with 0.5 confidence."""
        hits = DLPEngine.scan_text("Number: 123456789 here")
        ssn_hits = [h for h in hits if h.entity_type == "ssn"]
        assert len(ssn_hits) >= 1
        assert ssn_hits[0].confidence == 0.5

    def test_no_ssn_in_clean_text(self) -> None:
        """No false-positive SSN hits for clean text."""
        hits = DLPEngine.scan_text("Hello world, no secrets here.")
        ssn_hits = [h for h in hits if h.entity_type == "ssn"]
        assert len(ssn_hits) == 0


# ═══════════════════════════════════════════════════════════════════
# Credit Card Detection
# ═══════════════════════════════════════════════════════════════════


class TestCreditCardDetection:
    """Tests for credit card pattern detection."""

    def test_detects_visa(self) -> None:
        """Detect Visa card number."""
        hits = DLPEngine.scan_text("Card: 4111111111111111")
        cc_hits = [h for h in hits if h.entity_type == "credit_card"]
        assert len(cc_hits) == 1
        assert cc_hits[0].confidence == 1.0

    def test_detects_mastercard(self) -> None:
        """Detect Mastercard number."""
        hits = DLPEngine.scan_text("MC: 5105105105105100")
        cc_hits = [h for h in hits if h.entity_type == "credit_card"]
        assert len(cc_hits) == 1

    def test_detects_amex(self) -> None:
        """Detect American Express card number."""
        hits = DLPEngine.scan_text("Amex: 371449635398431")
        cc_hits = [h for h in hits if h.entity_type == "credit_card"]
        assert len(cc_hits) == 1

    def test_detects_discover(self) -> None:
        """Detect Discover card number."""
        hits = DLPEngine.scan_text("Discover: 6011111111111117")
        cc_hits = [h for h in hits if h.entity_type == "credit_card"]
        assert len(cc_hits) == 1

    def test_detects_card_with_dashes(self) -> None:
        """Detect card number with dashes."""
        hits = DLPEngine.scan_text("Visa: 4111-1111-1111-1111")
        cc_hits = [h for h in hits if h.entity_type == "credit_card"]
        assert len(cc_hits) == 1

    def test_detects_card_with_spaces(self) -> None:
        """Detect card number with spaces."""
        hits = DLPEngine.scan_text("Visa: 4111 1111 1111 1111")
        cc_hits = [h for h in hits if h.entity_type == "credit_card"]
        assert len(cc_hits) == 1


# ═══════════════════════════════════════════════════════════════════
# Email Detection
# ═══════════════════════════════════════════════════════════════════


class TestEmailDetection:
    """Tests for email address detection."""

    def test_detects_standard_email(self) -> None:
        """Detect a standard email address."""
        hits = DLPEngine.scan_text("Contact: user@example.com for info.")
        email_hits = [h for h in hits if h.entity_type == "email"]
        assert len(email_hits) == 1
        assert email_hits[0].confidence == 0.95
        assert email_hits[0].matched_text == "user@example.com"

    def test_detects_email_with_plus(self) -> None:
        """Detect email with plus-addressing."""
        hits = DLPEngine.scan_text("Send to user+tag@example.com")
        email_hits = [h for h in hits if h.entity_type == "email"]
        assert len(email_hits) == 1

    def test_no_email_false_positive(self) -> None:
        """No false-positive email for non-email text."""
        hits = DLPEngine.scan_text("This has no email addresses.")
        email_hits = [h for h in hits if h.entity_type == "email"]
        assert len(email_hits) == 0


# ═══════════════════════════════════════════════════════════════════
# API Key Detection
# ═══════════════════════════════════════════════════════════════════


class TestAPIKeyDetection:
    """Tests for API key pattern detection."""

    def test_detects_aws_access_key(self) -> None:
        """Detect an AWS access key (AKIA prefix)."""
        hits = DLPEngine.scan_text("Key: AKIAIOSFODNN7EXAMPLE")
        api_hits = [h for h in hits if h.entity_type == "api_key"]
        assert len(api_hits) == 1
        assert api_hits[0].confidence == 1.0

    def test_detects_generic_api_key(self) -> None:
        """Detect a generic api_key=<value> pattern."""
        hits = DLPEngine.scan_text("api_key=sk_live_abcdefgh1234567890AB")
        api_hits = [h for h in hits if h.entity_type == "api_key"]
        assert len(api_hits) == 1
        assert api_hits[0].confidence == 0.85

    def test_detects_secret_key_label(self) -> None:
        """Detect secret_key label with value."""
        hits = DLPEngine.scan_text('secret_key: "MyS3cretK3yValue12345"')
        api_hits = [h for h in hits if h.entity_type == "api_key"]
        assert len(api_hits) == 1


# ═══════════════════════════════════════════════════════════════════
# Password Detection
# ═══════════════════════════════════════════════════════════════════


class TestPasswordDetection:
    """Tests for password pattern detection."""

    def test_detects_password_equals(self) -> None:
        """Detect password=<value> pattern."""
        hits = DLPEngine.scan_text("password=SuperSecret123!")
        pw_hits = [h for h in hits if h.entity_type == "password"]
        assert len(pw_hits) == 1
        assert pw_hits[0].confidence == 0.9

    def test_detects_pwd_colon(self) -> None:
        """Detect pwd: <value> pattern."""
        hits = DLPEngine.scan_text("pwd: my_password_value")
        pw_hits = [h for h in hits if h.entity_type == "password"]
        assert len(pw_hits) == 1

    def test_detects_passwd_with_quotes(self) -> None:
        """Detect passwd="<value>" pattern."""
        hits = DLPEngine.scan_text('passwd="hunter2"')
        pw_hits = [h for h in hits if h.entity_type == "password"]
        assert len(pw_hits) == 1

    def test_no_password_false_positive(self) -> None:
        """No detection when 'password' is not followed by a value."""
        hits = DLPEngine.scan_text("Forgot your password?")
        pw_hits = [h for h in hits if h.entity_type == "password"]
        assert len(pw_hits) == 0


# ═══════════════════════════════════════════════════════════════════
# Redaction
# ═══════════════════════════════════════════════════════════════════


class TestRedaction:
    """Tests for DLPEngine.redact_text."""

    def test_redacts_ssn(self) -> None:
        """SSN in text is replaced by redaction template."""
        redacted, hits = DLPEngine.redact_text("SSN: 123-45-6789 ok")
        assert "123-45-6789" not in redacted
        assert "***-**-****" in redacted
        assert len(hits) >= 1

    def test_redacts_email(self) -> None:
        """Email in text is replaced by [EMAIL REDACTED]."""
        redacted, hits = DLPEngine.redact_text("Email: user@test.com here")
        assert "user@test.com" not in redacted
        assert "[EMAIL REDACTED]" in redacted

    def test_redacts_credit_card(self) -> None:
        """Credit card in text is replaced by redaction template."""
        redacted, hits = DLPEngine.redact_text("Card: 4111111111111111 end")
        assert "4111111111111111" not in redacted
        assert "****-****-****-****" in redacted

    def test_redacts_multiple_entities(self) -> None:
        """Multiple entities in one text are all redacted."""
        text = "SSN 123-45-6789 and email user@test.com"
        redacted, hits = DLPEngine.redact_text(text)
        assert "123-45-6789" not in redacted
        assert "user@test.com" not in redacted
        assert len(hits) >= 2

    def test_no_redaction_clean_text(self) -> None:
        """Clean text is returned unchanged with empty hit list."""
        text = "Nothing sensitive here."
        redacted, hits = DLPEngine.redact_text(text)
        assert redacted == text
        assert hits == []

    def test_redaction_preserves_surrounding_text(self) -> None:
        """Text before and after the match is preserved."""
        text = "before 123-45-6789 after"
        redacted, _ = DLPEngine.redact_text(text)
        assert redacted.startswith("before ")
        assert redacted.endswith(" after")


# ═══════════════════════════════════════════════════════════════════
# Detector Type Filtering
# ═══════════════════════════════════════════════════════════════════


class TestDetectorTypeFiltering:
    """Tests for the detector_types parameter on scan_text."""

    def test_filter_to_ssn_only(self) -> None:
        """When detector_types=['ssn'], only SSN is detected."""
        text = "SSN 123-45-6789 card 4111111111111111 email a@b.com"
        hits = DLPEngine.scan_text(text, detector_types=["ssn"])
        types = {h.entity_type for h in hits}
        assert "ssn" in types
        assert "credit_card" not in types
        assert "email" not in types

    def test_filter_to_email_only(self) -> None:
        """When detector_types=['email'], only email is detected."""
        text = "SSN 123-45-6789 email user@example.com"
        hits = DLPEngine.scan_text(text, detector_types=["email"])
        types = {h.entity_type for h in hits}
        assert "email" in types
        assert "ssn" not in types

    def test_empty_detector_types_falls_back_to_all(self) -> None:
        """Empty list is falsy — falls back to all built-in detectors."""
        text = "SSN 123-45-6789 email user@example.com"
        hits = DLPEngine.scan_text(text, detector_types=[])
        types = {h.entity_type for h in hits}
        assert "ssn" in types
        assert "email" in types


# ═══════════════════════════════════════════════════════════════════
# Custom Patterns
# ═══════════════════════════════════════════════════════════════════


class TestCustomPatterns:
    """Tests for custom_patterns support in scan_text."""

    def test_custom_pattern_detected(self) -> None:
        """Custom regex pattern produces hits with 0.8 confidence."""
        hits = DLPEngine.scan_text(
            "Employee EMP-123456 is active",
            custom_patterns={"employee_id": r"EMP-\d{6}"},
        )
        emp_hits = [h for h in hits if h.entity_type == "employee_id"]
        assert len(emp_hits) == 1
        assert emp_hits[0].confidence == 0.8
        assert emp_hits[0].redacted == "[EMPLOYEE_ID REDACTED]"

    def test_invalid_custom_regex_skipped(self) -> None:
        """Invalid regex in custom_patterns is silently skipped."""
        hits = DLPEngine.scan_text(
            "Hello world",
            custom_patterns={"bad": r"[invalid("},
        )
        assert isinstance(hits, list)  # no exception raised

    def test_custom_pattern_redaction(self) -> None:
        """Custom pattern hit is redacted correctly."""
        redacted, hits = DLPEngine.redact_text(
            "ID: EMP-999999 end",
            custom_patterns={"employee_id": r"EMP-\d{6}"},
        )
        assert "EMP-999999" not in redacted
        assert "[EMPLOYEE_ID REDACTED]" in redacted


# ═══════════════════════════════════════════════════════════════════
# Min Confidence Filtering
# ═══════════════════════════════════════════════════════════════════


class TestMinConfidenceFiltering:
    """Tests for min_confidence parameter."""

    def test_high_threshold_filters_low_confidence(self) -> None:
        """Bare 9-digit SSN (conf=0.5) is filtered at min_confidence=0.9."""
        hits = DLPEngine.scan_text("Num 123456789 here", min_confidence=0.9)
        ssn_hits = [h for h in hits if h.entity_type == "ssn"]
        assert len(ssn_hits) == 0

    def test_low_threshold_keeps_all(self) -> None:
        """min_confidence=0.0 keeps everything."""
        hits = DLPEngine.scan_text("SSN 123-45-6789", min_confidence=0.0)
        assert len(hits) >= 1

    def test_exact_threshold_keeps_match(self) -> None:
        """Hit at exactly min_confidence boundary is NOT filtered (conf < min_confidence filters)."""
        # Email confidence is 0.95; min_confidence=0.95 should keep it
        # because the code does `if confidence < min_confidence: continue`
        hits = DLPEngine.scan_text("a@b.com", min_confidence=0.95)
        email_hits = [h for h in hits if h.entity_type == "email"]
        assert len(email_hits) == 1

    def test_threshold_just_above_filters(self) -> None:
        """min_confidence just above hit confidence filters it out."""
        hits = DLPEngine.scan_text("a@b.com", min_confidence=0.96)
        email_hits = [h for h in hits if h.entity_type == "email"]
        assert len(email_hits) == 0

    def test_redact_text_respects_min_confidence(self) -> None:
        """redact_text passes min_confidence through to scan_text."""
        text = "Num 123456789 and SSN 123-45-6789"
        redacted, hits = DLPEngine.redact_text(text, min_confidence=0.9)
        # Bare 9-digit (0.5 conf) should NOT be redacted
        # Formatted SSN (1.0 conf) should still be redacted
        assert "***-**-****" in redacted
        confidences = [h.confidence for h in hits]
        assert all(c >= 0.9 for c in confidences)


# ═══════════════════════════════════════════════════════════════════
# DetectionHit Serialisation
# ═══════════════════════════════════════════════════════════════════


class TestDetectionHitSerialization:
    """Tests for DetectionHit.to_dict."""

    def test_to_dict_excludes_matched_text(self) -> None:
        """to_dict never leaks raw matched_text."""
        hit = DetectionHit(
            entity_type="ssn",
            start=0,
            end=11,
            matched_text="123-45-6789",
            confidence=1.0,
            redacted="***-**-****",
        )
        d = hit.to_dict()
        assert "matched_text" not in d
        assert d["entity_type"] == "ssn"
        assert d["confidence"] == 1.0
        assert d["redacted_value"] == "***-**-****"
        assert d["start"] == 0
        assert d["end"] == 11

    def test_to_dict_keys(self) -> None:
        """to_dict returns exactly the expected keys."""
        hit = DetectionHit("email", 0, 10, "a@b.com", 0.95, "[EMAIL REDACTED]")
        assert set(hit.to_dict().keys()) == {
            "entity_type", "start", "end", "confidence", "redacted_value",
        }


# ═══════════════════════════════════════════════════════════════════
# Overlap Deduplication
# ═══════════════════════════════════════════════════════════════════


class TestOverlapDeduplication:
    """Tests for overlapping hit deduplication logic."""

    def test_overlapping_patterns_keep_higher_confidence(self) -> None:
        """When formatted SSN overlaps with bare 9-digit, the higher confidence wins."""
        # "123-45-6789" is 11 chars; the bare 9-digit "123456789" would overlap
        # but since there are dashes, only the formatted SSN should match
        hits = DLPEngine.scan_text("SSN: 123-45-6789")
        ssn_hits = [h for h in hits if h.entity_type == "ssn"]
        assert len(ssn_hits) == 1
        assert ssn_hits[0].confidence == 1.0

    def test_non_overlapping_both_kept(self) -> None:
        """Two non-overlapping detections are both returned."""
        text = "SSN 123-45-6789 and email user@test.com"
        hits = DLPEngine.scan_text(text)
        types = {h.entity_type for h in hits}
        assert "ssn" in types
        assert "email" in types


# ═══════════════════════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge case tests for scan_text and redact_text."""

    def test_empty_string(self) -> None:
        """Empty string returns no hits."""
        hits = DLPEngine.scan_text("")
        assert hits == []

    def test_empty_string_redact(self) -> None:
        """Empty string returns unchanged with no hits."""
        redacted, hits = DLPEngine.redact_text("")
        assert redacted == ""
        assert hits == []

    def test_very_long_text_without_matches(self) -> None:
        """Large clean text returns no hits quickly."""
        text = "clean text " * 10_000
        hits = DLPEngine.scan_text(text)
        assert hits == []

    def test_multiple_ssns_in_text(self) -> None:
        """Multiple SSNs detected separately."""
        text = "SSN1: 111-22-3333, SSN2: 444-55-6666"
        hits = DLPEngine.scan_text(text)
        ssn_hits = [h for h in hits if h.entity_type == "ssn"]
        assert len(ssn_hits) == 2

    def test_unknown_detector_type_no_crash(self) -> None:
        """Requesting an unknown detector type simply returns no hits."""
        hits = DLPEngine.scan_text("Hello", detector_types=["nonexistent"])
        assert hits == []


# ═══════════════════════════════════════════════════════════════════
# Policy CRUD (async, DB-backed)
# ═══════════════════════════════════════════════════════════════════


class TestPolicyCRUD:
    """Tests for DLPEngine policy CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_policy(self) -> None:
        """create_policy adds to session, commits, and refreshes."""
        session = _mock_session()
        policy = _policy()
        result = await DLPEngine.create_policy(session, policy)

        session.add.assert_called_once_with(policy)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(policy)
        assert result is policy

    @pytest.mark.asyncio
    async def test_get_policy_found(self) -> None:
        """get_policy returns the policy when found."""
        session = _mock_session()
        policy = _policy()
        session.get = AsyncMock(return_value=policy)

        result = await DLPEngine.get_policy(session, POLICY_ID)
        session.get.assert_awaited_once_with(DLPPolicy, POLICY_ID)
        assert result is policy

    @pytest.mark.asyncio
    async def test_get_policy_not_found(self) -> None:
        """get_policy returns None when not found."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await DLPEngine.get_policy(session, POLICY_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_list_policies(self) -> None:
        """list_policies returns paginated results and total count."""
        session = _mock_session()
        p1, p2 = _policy(name="A"), _policy(name="B", pid=uuid4())
        session.exec = AsyncMock(side_effect=[
            _exec_result([p1, p2]),  # count query
            _exec_result([p1]),       # paginated query
        ])

        policies, total = await DLPEngine.list_policies(session, limit=1, offset=0)
        assert total == 2
        assert len(policies) == 1
        assert policies[0].name == "A"

    @pytest.mark.asyncio
    async def test_list_policies_active_filter(self) -> None:
        """list_policies filters by is_active."""
        session = _mock_session()
        active = _policy(is_active=True)
        session.exec = AsyncMock(side_effect=[
            _exec_result([active]),  # count
            _exec_result([active]),  # paginated
        ])

        policies, total = await DLPEngine.list_policies(
            session, is_active=True, limit=20, offset=0,
        )
        assert total == 1
        assert policies[0].is_active is True

    @pytest.mark.asyncio
    async def test_update_policy_found(self) -> None:
        """update_policy applies changes and commits."""
        session = _mock_session()
        policy = _policy(name="Old Name")
        session.get = AsyncMock(return_value=policy)

        result = await DLPEngine.update_policy(
            session, POLICY_ID, {"name": "New Name"},
        )
        assert result is not None
        assert result.name == "New Name"
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_policy_not_found(self) -> None:
        """update_policy returns None when policy doesn't exist."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await DLPEngine.update_policy(session, POLICY_ID, {"name": "X"})
        assert result is None
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_policy_ignores_unknown_fields(self) -> None:
        """update_policy silently ignores keys that aren't model attributes."""
        session = _mock_session()
        policy = _policy()
        session.get = AsyncMock(return_value=policy)

        result = await DLPEngine.update_policy(
            session, POLICY_ID, {"nonexistent_field": "value"},
        )
        assert result is policy
        assert not hasattr(result, "nonexistent_field")

    @pytest.mark.asyncio
    async def test_delete_policy_found(self) -> None:
        """delete_policy deletes and commits, returns True."""
        session = _mock_session()
        policy = _policy()
        session.get = AsyncMock(return_value=policy)

        result = await DLPEngine.delete_policy(session, POLICY_ID)
        assert result is True
        session.delete.assert_awaited_once_with(policy)
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_policy_not_found(self) -> None:
        """delete_policy returns False when policy doesn't exist."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await DLPEngine.delete_policy(session, POLICY_ID)
        assert result is False
        session.commit.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════
# Scan and Record (async, DB-backed)
# ═══════════════════════════════════════════════════════════════════


class TestScanAndRecord:
    """Tests for DLPEngine.scan_and_record."""

    @pytest.mark.asyncio
    async def test_scan_and_record_with_findings(self) -> None:
        """scan_and_record persists scan result and entities for text with SSN."""
        session = _mock_session()
        text = "SSN: 123-45-6789"

        result = await DLPEngine.scan_and_record(session, text, source="input")

        assert result.has_findings is True
        assert result.findings_count >= 1
        assert result.source == "input"
        assert result.text_hash == hashlib.sha256(text.encode()).hexdigest()
        assert "ssn" in result.entity_types_found
        session.flush.assert_awaited_once()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()
        # At least 2 add calls: 1 for scan_result + 1 for each entity
        assert session.add.call_count >= 2

    @pytest.mark.asyncio
    async def test_scan_and_record_no_findings(self) -> None:
        """scan_and_record with clean text has no findings."""
        session = _mock_session()
        text = "No sensitive data here."

        result = await DLPEngine.scan_and_record(session, text)

        assert result.has_findings is False
        assert result.findings_count == 0
        assert result.action_taken == "none"
        assert result.entity_types_found == []
        # Only 1 add call for the scan_result itself
        assert session.add.call_count == 1

    @pytest.mark.asyncio
    async def test_scan_and_record_with_policy(self) -> None:
        """scan_and_record with policy_id applies policy settings."""
        session = _mock_session()
        policy = _policy(
            detector_types=["ssn"],
            action="block",
        )
        session.get = AsyncMock(return_value=policy)
        text = "SSN: 123-45-6789 email: user@test.com"

        result = await DLPEngine.scan_and_record(
            session, text, policy_id=POLICY_ID,
        )

        assert result.policy_id == POLICY_ID
        assert result.action_taken == "block"
        # Only SSN detector should have run (policy restricts)
        assert "ssn" in result.entity_types_found

    @pytest.mark.asyncio
    async def test_scan_and_record_inactive_policy_ignored(self) -> None:
        """Inactive policy is ignored — all detectors run, action=none."""
        session = _mock_session()
        policy = _policy(is_active=False, action="block")
        session.get = AsyncMock(return_value=policy)
        text = "SSN: 123-45-6789"

        result = await DLPEngine.scan_and_record(
            session, text, policy_id=POLICY_ID,
        )

        # Inactive policy → all detectors run, action falls back to "none"
        assert result.has_findings is True
        assert result.action_taken == "none"

    @pytest.mark.asyncio
    async def test_scan_and_record_policy_not_found(self) -> None:
        """Missing policy_id → all detectors run, action=none."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)
        text = "SSN: 123-45-6789"

        result = await DLPEngine.scan_and_record(
            session, text, policy_id=POLICY_ID,
        )

        assert result.has_findings is True
        assert result.action_taken == "none"

    @pytest.mark.asyncio
    async def test_scan_and_record_never_stores_raw_text(self) -> None:
        """Raw text is never stored — only a SHA-256 hash."""
        session = _mock_session()
        text = "SSN: 123-45-6789 super secret"

        result = await DLPEngine.scan_and_record(session, text)

        assert text not in str(result.text_hash)
        assert result.text_hash == hashlib.sha256(text.encode()).hexdigest()

    @pytest.mark.asyncio
    async def test_scan_and_record_with_custom_patterns_via_policy(self) -> None:
        """Policy custom_patterns are passed through to scan_text."""
        session = _mock_session()
        policy = _policy(
            detector_types=[],  # no built-in detectors
            custom_patterns={"emp_id": r"EMP-\d{6}"},
            action="alert",
        )
        session.get = AsyncMock(return_value=policy)
        text = "Employee EMP-123456 active"

        result = await DLPEngine.scan_and_record(
            session, text, policy_id=POLICY_ID,
        )

        assert result.has_findings is True
        assert "emp_id" in result.entity_types_found
        assert result.action_taken == "alert"

    @pytest.mark.asyncio
    async def test_scan_and_record_default_source(self) -> None:
        """Default source is 'manual'."""
        session = _mock_session()
        result = await DLPEngine.scan_and_record(session, "clean text")
        assert result.source == "manual"
