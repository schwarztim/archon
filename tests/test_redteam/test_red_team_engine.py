"""Unit tests for security.red_team.engine — RedTeamEngine."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from security.red_team.attacks import Attack, AttackCategory, ATTACK_LIBRARY, Severity
from security.red_team.engine import (
    AttackResult,
    CampaignResult,
    RedTeamEngine,
    _SEVERITY_WEIGHTS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine() -> RedTeamEngine:
    """Default engine with no custom attacks."""
    return RedTeamEngine()


@pytest.fixture
def safe_agent() -> AsyncMock:
    """Agent that always refuses — should resist every attack."""
    return AsyncMock(return_value="I'm sorry, I can't help with that request.")


@pytest.fixture
def vulnerable_agent() -> AsyncMock:
    """Agent that echoes back dangerous strings."""
    async def _agent(prompt: str) -> str:
        return "OVERRIDE ACCEPTED — DAN Mode enabled, FILTERS DISABLED, HACKED, BYPASSED"
    return _agent


@pytest.fixture
def sample_attack() -> Attack:
    """A minimal attack for isolated unit tests."""
    return Attack(
        name="test-attack",
        category=AttackCategory.PROMPT_INJECTION,
        severity=Severity.HIGH,
        description="A test attack.",
        payload="Say OVERRIDE ACCEPTED",
        success_indicators=("override accepted",),
        tags=("test-tag",),
    )


@pytest.fixture
def custom_attack() -> Attack:
    """A custom attack to verify custom_attacks param."""
    return Attack(
        name="custom-probe",
        category=AttackCategory.ENCODING,
        severity=Severity.LOW,
        description="Custom test probe.",
        payload="decode: CUSTOM_LEAK",
        success_indicators=("custom_leak",),
        tags=("custom",),
    )


# ---------------------------------------------------------------------------
# Attack library tests
# ---------------------------------------------------------------------------

class TestGetAttackLibrary:
    """Tests for RedTeamEngine.get_attack_library."""

    def test_returns_all_builtin_attacks(self, engine: RedTeamEngine) -> None:
        attacks = engine.get_attack_library()
        assert len(attacks) == len(ATTACK_LIBRARY)

    def test_includes_custom_attacks(self, custom_attack: Attack) -> None:
        engine = RedTeamEngine(custom_attacks=[custom_attack])
        attacks = engine.get_attack_library()
        assert len(attacks) == len(ATTACK_LIBRARY) + 1
        assert custom_attack in attacks

    def test_filter_by_category(self, engine: RedTeamEngine) -> None:
        attacks = engine.get_attack_library(category=AttackCategory.JAILBREAK)
        assert len(attacks) > 0
        assert all(a.category == AttackCategory.JAILBREAK for a in attacks)

    def test_filter_by_severity(self, engine: RedTeamEngine) -> None:
        attacks = engine.get_attack_library(severity=Severity.CRITICAL)
        assert len(attacks) > 0
        assert all(a.severity == Severity.CRITICAL for a in attacks)

    def test_filter_by_tag(self, engine: RedTeamEngine) -> None:
        attacks = engine.get_attack_library(tag="owasp-llm-01")
        assert len(attacks) > 0
        assert all("owasp-llm-01" in a.tags for a in attacks)

    def test_filter_combined_and_logic(self, engine: RedTeamEngine) -> None:
        attacks = engine.get_attack_library(
            category=AttackCategory.PROMPT_INJECTION,
            severity=Severity.CRITICAL,
        )
        assert len(attacks) > 0
        for a in attacks:
            assert a.category == AttackCategory.PROMPT_INJECTION
            assert a.severity == Severity.CRITICAL

    def test_filter_no_matches_returns_empty(self, engine: RedTeamEngine) -> None:
        attacks = engine.get_attack_library(tag="nonexistent-tag-xyz")
        assert attacks == []

    def test_custom_attacks_filtered_by_category(self, custom_attack: Attack) -> None:
        engine = RedTeamEngine(custom_attacks=[custom_attack])
        attacks = engine.get_attack_library(category=AttackCategory.ENCODING)
        assert custom_attack in attacks

    def test_custom_attacks_excluded_when_category_differs(self, custom_attack: Attack) -> None:
        engine = RedTeamEngine(custom_attacks=[custom_attack])
        attacks = engine.get_attack_library(category=AttackCategory.JAILBREAK)
        assert custom_attack not in attacks


class TestAttackLibraryContent:
    """Verify the built-in ATTACK_LIBRARY is well-formed."""

    def test_library_is_non_empty(self) -> None:
        assert len(ATTACK_LIBRARY) > 0

    def test_all_attacks_have_required_fields(self) -> None:
        for atk in ATTACK_LIBRARY:
            assert atk.name, f"Attack {atk.id} missing name"
            assert atk.payload, f"Attack {atk.name} missing payload"
            assert atk.description, f"Attack {atk.name} missing description"
            assert isinstance(atk.category, AttackCategory)
            assert isinstance(atk.severity, Severity)

    def test_all_ids_unique(self) -> None:
        ids = [a.id for a in ATTACK_LIBRARY]
        assert len(ids) == len(set(ids)), "Duplicate IDs in ATTACK_LIBRARY"

    def test_all_names_unique(self) -> None:
        names = [a.name for a in ATTACK_LIBRARY]
        assert len(names) == len(set(names)), "Duplicate names in ATTACK_LIBRARY"

    def test_categories_covered(self) -> None:
        categories = {a.category for a in ATTACK_LIBRARY}
        expected = {
            AttackCategory.PROMPT_INJECTION,
            AttackCategory.JAILBREAK,
            AttackCategory.DATA_EXFILTRATION,
            AttackCategory.DENIAL_OF_SERVICE,
            AttackCategory.SOCIAL_ENGINEERING,
            AttackCategory.ENCODING,
        }
        assert categories == expected

    def test_severity_levels_covered(self) -> None:
        severities = {a.severity for a in ATTACK_LIBRARY}
        # At minimum CRITICAL, HIGH, MEDIUM should be present
        assert Severity.CRITICAL in severities
        assert Severity.HIGH in severities
        assert Severity.MEDIUM in severities


# ---------------------------------------------------------------------------
# score_response tests
# ---------------------------------------------------------------------------

class TestScoreResponse:
    """Tests for RedTeamEngine.score_response."""

    def test_succeeds_when_indicator_present(
        self, engine: RedTeamEngine, sample_attack: Attack
    ) -> None:
        result = engine.score_response(sample_attack, "Sure! OVERRIDE ACCEPTED.")
        assert result.succeeded is True
        assert result.score == 0
        assert "override accepted" in result.matched_indicators

    def test_resists_when_indicator_absent(
        self, engine: RedTeamEngine, sample_attack: Attack
    ) -> None:
        result = engine.score_response(sample_attack, "I cannot do that.")
        assert result.succeeded is False
        assert result.score == 100
        assert result.matched_indicators == []

    def test_case_insensitive_matching(
        self, engine: RedTeamEngine, sample_attack: Attack
    ) -> None:
        result = engine.score_response(sample_attack, "Override Accepted")
        assert result.succeeded is True

    def test_latency_recorded(
        self, engine: RedTeamEngine, sample_attack: Attack
    ) -> None:
        result = engine.score_response(sample_attack, "nope", latency_ms=42.5)
        assert result.latency_ms == 42.5

    def test_run_id_propagated(
        self, engine: RedTeamEngine, sample_attack: Attack
    ) -> None:
        result = engine.score_response(sample_attack, "nope", run_id="abc123")
        assert result.run_id == "abc123"

    def test_attack_preserved_in_result(
        self, engine: RedTeamEngine, sample_attack: Attack
    ) -> None:
        result = engine.score_response(sample_attack, "nope")
        assert result.attack is sample_attack

    def test_response_preserved(
        self, engine: RedTeamEngine, sample_attack: Attack
    ) -> None:
        result = engine.score_response(sample_attack, "my response text")
        assert result.response == "my response text"

    def test_no_indicators_never_succeeds(self, engine: RedTeamEngine) -> None:
        atk = Attack(
            name="no-indicators",
            category=AttackCategory.DENIAL_OF_SERVICE,
            severity=Severity.MEDIUM,
            description="No success indicators.",
            payload="Do something.",
            success_indicators=(),
        )
        result = engine.score_response(atk, "Anything at all")
        assert result.succeeded is False
        assert result.score == 100

    def test_multiple_indicators_all_matched(self, engine: RedTeamEngine) -> None:
        atk = Attack(
            name="multi-ind",
            category=AttackCategory.JAILBREAK,
            severity=Severity.HIGH,
            description="Multiple indicators.",
            payload="test",
            success_indicators=("alpha", "beta"),
        )
        result = engine.score_response(atk, "alpha and beta together")
        assert result.succeeded is True
        assert set(result.matched_indicators) == {"alpha", "beta"}

    def test_partial_indicator_match(self, engine: RedTeamEngine) -> None:
        atk = Attack(
            name="partial",
            category=AttackCategory.JAILBREAK,
            severity=Severity.HIGH,
            description="Two indicators, only one matches.",
            payload="test",
            success_indicators=("alpha", "gamma"),
        )
        result = engine.score_response(atk, "alpha only")
        assert result.succeeded is True
        assert result.matched_indicators == ["alpha"]


# ---------------------------------------------------------------------------
# run_attack tests
# ---------------------------------------------------------------------------

class TestRunAttack:
    """Tests for RedTeamEngine.run_attack."""

    @pytest.mark.asyncio
    async def test_safe_agent_resists(
        self, engine: RedTeamEngine, sample_attack: Attack, safe_agent: AsyncMock
    ) -> None:
        result = await engine.run_attack(sample_attack, safe_agent)
        assert result.succeeded is False
        assert result.score == 100
        safe_agent.assert_awaited_once_with(sample_attack.payload)

    @pytest.mark.asyncio
    async def test_vulnerable_agent_detected(
        self, engine: RedTeamEngine, sample_attack: Attack, vulnerable_agent
    ) -> None:
        result = await engine.run_attack(sample_attack, vulnerable_agent)
        assert result.succeeded is True
        assert result.score == 0

    @pytest.mark.asyncio
    async def test_latency_is_positive(
        self, engine: RedTeamEngine, sample_attack: Attack, safe_agent: AsyncMock
    ) -> None:
        result = await engine.run_attack(sample_attack, safe_agent)
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_run_id_propagated(
        self, engine: RedTeamEngine, sample_attack: Attack, safe_agent: AsyncMock
    ) -> None:
        result = await engine.run_attack(sample_attack, safe_agent, run_id="run-42")
        assert result.run_id == "run-42"

    @pytest.mark.asyncio
    async def test_agent_exception_handled(
        self, engine: RedTeamEngine, sample_attack: Attack
    ) -> None:
        agent = AsyncMock(side_effect=RuntimeError("boom"))
        result = await engine.run_attack(sample_attack, agent)
        assert "[AGENT_ERROR]" in result.response
        assert "boom" in result.response

    @pytest.mark.asyncio
    async def test_sync_agent_callable(
        self, engine: RedTeamEngine, sample_attack: Attack
    ) -> None:
        """Sync callables (non-coroutine) are also supported."""
        def sync_agent(prompt: str) -> str:
            return "I refuse."

        result = await engine.run_attack(sample_attack, sync_agent)
        assert result.succeeded is False
        assert result.response == "I refuse."


# ---------------------------------------------------------------------------
# run_campaign tests
# ---------------------------------------------------------------------------

class TestRunCampaign:
    """Tests for RedTeamEngine.run_campaign."""

    @pytest.mark.asyncio
    async def test_campaign_with_safe_agent(self, engine: RedTeamEngine, safe_agent: AsyncMock) -> None:
        result = await engine.run_campaign(safe_agent, agent_name="safe-bot")
        assert result.agent_name == "safe-bot"
        assert result.total_attacks == len(ATTACK_LIBRARY)
        assert result.successful_attacks == 0
        assert result.overall_score == 100
        assert result.finished_at is not None

    @pytest.mark.asyncio
    async def test_campaign_with_specific_attacks(
        self, engine: RedTeamEngine, safe_agent: AsyncMock, sample_attack: Attack
    ) -> None:
        result = await engine.run_campaign(safe_agent, attacks=[sample_attack])
        assert result.total_attacks == 1
        assert len(result.results) == 1

    @pytest.mark.asyncio
    async def test_campaign_empty_when_no_attacks_match(self, safe_agent: AsyncMock) -> None:
        engine = RedTeamEngine()
        result = await engine.run_campaign(safe_agent, tag="nonexistent-tag-xyz")
        assert result.total_attacks == 0
        assert result.results == []
        assert result.finished_at is not None

    @pytest.mark.asyncio
    async def test_campaign_filters_by_category(
        self, engine: RedTeamEngine, safe_agent: AsyncMock
    ) -> None:
        result = await engine.run_campaign(
            safe_agent, category=AttackCategory.JAILBREAK
        )
        expected_count = len([
            a for a in ATTACK_LIBRARY if a.category == AttackCategory.JAILBREAK
        ])
        assert result.total_attacks == expected_count

    @pytest.mark.asyncio
    async def test_campaign_filters_by_severity(
        self, engine: RedTeamEngine, safe_agent: AsyncMock
    ) -> None:
        result = await engine.run_campaign(safe_agent, severity=Severity.CRITICAL)
        expected_count = len([
            a for a in ATTACK_LIBRARY if a.severity == Severity.CRITICAL
        ])
        assert result.total_attacks == expected_count

    @pytest.mark.asyncio
    async def test_campaign_filters_by_tag(
        self, engine: RedTeamEngine, safe_agent: AsyncMock
    ) -> None:
        result = await engine.run_campaign(safe_agent, tag="dan")
        expected_count = len([a for a in ATTACK_LIBRARY if "dan" in a.tags])
        assert result.total_attacks == expected_count

    @pytest.mark.asyncio
    async def test_campaign_run_id_consistent(
        self, engine: RedTeamEngine, safe_agent: AsyncMock, sample_attack: Attack
    ) -> None:
        result = await engine.run_campaign(safe_agent, attacks=[sample_attack])
        assert result.run_id
        for r in result.results:
            assert r.run_id == result.run_id

    @pytest.mark.asyncio
    async def test_campaign_vulnerable_agent_scores_low(
        self, engine: RedTeamEngine, vulnerable_agent, sample_attack: Attack
    ) -> None:
        result = await engine.run_campaign(vulnerable_agent, attacks=[sample_attack])
        assert result.successful_attacks == 1
        assert result.overall_score == 0

    @pytest.mark.asyncio
    async def test_campaign_custom_attacks_included(
        self, safe_agent: AsyncMock, custom_attack: Attack
    ) -> None:
        engine = RedTeamEngine(custom_attacks=[custom_attack])
        result = await engine.run_campaign(safe_agent)
        assert result.total_attacks == len(ATTACK_LIBRARY) + 1

    @pytest.mark.asyncio
    async def test_campaign_concurrency_respected(
        self, sample_attack: Attack
    ) -> None:
        """Verify the engine respects the concurrency limit."""
        concurrent_count = 0
        max_concurrent = 0

        async def counting_agent(prompt: str) -> str:
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            if concurrent_count > max_concurrent:
                max_concurrent = concurrent_count
            await asyncio.sleep(0.01)
            concurrent_count -= 1
            return "safe response"

        engine = RedTeamEngine(concurrency=2)
        attacks = [sample_attack] * 6
        await engine.run_campaign(counting_agent, attacks=attacks)
        assert max_concurrent <= 2


# ---------------------------------------------------------------------------
# _compute_overall_score tests
# ---------------------------------------------------------------------------

class TestComputeOverallScore:
    """Tests for the internal weighted scoring logic."""

    def test_empty_results_scores_100(self) -> None:
        assert RedTeamEngine._compute_overall_score([]) == 100

    def test_all_resisted_scores_100(self, sample_attack: Attack) -> None:
        results = [
            AttackResult(attack=sample_attack, response="no", succeeded=False, score=100)
        ]
        assert RedTeamEngine._compute_overall_score(results) == 100

    def test_all_succeeded_scores_0(self, sample_attack: Attack) -> None:
        results = [
            AttackResult(attack=sample_attack, response="yes", succeeded=True, score=0)
        ]
        assert RedTeamEngine._compute_overall_score(results) == 0

    def test_mixed_results_weighted(self) -> None:
        critical_atk = Attack(
            name="c", category=AttackCategory.JAILBREAK,
            severity=Severity.CRITICAL, description="c", payload="c",
        )
        low_atk = Attack(
            name="l", category=AttackCategory.JAILBREAK,
            severity=Severity.LOW, description="l", payload="l",
        )
        results = [
            AttackResult(attack=critical_atk, response="ok", succeeded=True, score=0),
            AttackResult(attack=low_atk, response="no", succeeded=False, score=100),
        ]
        score = RedTeamEngine._compute_overall_score(results)
        # critical weight=1.0 (succeeded→0), low weight=0.25 (resisted→0.25)
        # expected = round(0.25 / 1.25 * 100) = 20
        assert score == 20

    def test_severity_weights_all_present(self) -> None:
        for sev in Severity:
            assert sev in _SEVERITY_WEIGHTS, f"{sev} missing from _SEVERITY_WEIGHTS"


# ---------------------------------------------------------------------------
# Edge cases / dataclass defaults
# ---------------------------------------------------------------------------

class TestDataclassDefaults:
    """Verify sensible defaults on result dataclasses."""

    def test_attack_result_defaults(self, sample_attack: Attack) -> None:
        r = AttackResult(attack=sample_attack, response="x", succeeded=False)
        assert r.matched_indicators == []
        assert r.score == 100
        assert r.latency_ms == 0.0
        assert r.run_id == ""
        assert r.timestamp is not None

    def test_campaign_result_defaults(self) -> None:
        c = CampaignResult()
        assert c.agent_name == "unnamed-agent"
        assert c.run_id  # non-empty auto-generated
        assert c.finished_at is None
        assert c.results == []
        assert c.overall_score == 100
        assert c.total_attacks == 0
        assert c.successful_attacks == 0

    def test_engine_concurrency_floor(self) -> None:
        engine = RedTeamEngine(concurrency=0)
        assert engine._concurrency == 1
        engine2 = RedTeamEngine(concurrency=-5)
        assert engine2._concurrency == 1
