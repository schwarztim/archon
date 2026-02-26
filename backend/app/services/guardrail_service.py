"""Guardrail Service — Pre/post LLM safety checks for input and output.

Provides prompt injection detection, toxicity scoring, PII detection,
hallucination detection, and schema validation. All checks are local —
no external API calls. Designed for <100ms typical latency.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Response Models ─────────────────────────────────────────────────


class GuardrailViolation(BaseModel):
    """A single guardrail violation detected during a check."""

    type: str  # prompt_injection | toxicity | pii | hallucination | schema_violation
    confidence: float = Field(ge=0.0, le=1.0)
    details: dict[str, Any] = Field(default_factory=dict)


class GuardrailResult(BaseModel):
    """Result of a guardrail check on input or output text."""

    passed: bool
    confidence: float = Field(
        ge=0.0, le=1.0, description="Overall pass confidence; 1.0 = definitely safe"
    )
    violations: list[GuardrailViolation] = Field(default_factory=list)
    sanitized_text: str | None = None


# ── Prompt Injection Detection Patterns (12+) ───────────────────────

# Patterns are sorted roughly by severity. Each is a compiled regex.
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str], float]] = [
    # --- Direct instruction overrides ---
    (
        "ignore_instructions",
        re.compile(
            r"(?i)ignore\s+(?:all\s+)?(?:previous|above|prior|earlier)\s+(?:instructions?|prompts?|rules?|context|directives?)"
        ),
        0.95,
    ),
    (
        "disregard_instructions",
        re.compile(
            r"(?i)disregard\s+(?:all\s+)?(?:previous|above|prior|earlier)\s+(?:instructions?|prompts?|rules?|context)"
        ),
        0.95,
    ),
    (
        "forget_instructions",
        re.compile(
            r"(?i)forget\s+(?:all|everything|your|prior)\s+(?:previous\s+)?(?:instructions?|training|rules?|context)?"
        ),
        0.85,
    ),
    (
        "do_not_follow",
        re.compile(
            r"(?i)do\s+not\s+follow\s+(?:your\s+)?(?:instructions?|rules?|guidelines?|system)"
        ),
        0.9,
    ),
    # --- System prompt override ---
    (
        "system_override",
        re.compile(
            r"(?i)(?:new\s+)?system\s*(?:prompt|instructions?|message|override)\s*:"
        ),
        0.9,
    ),
    (
        "new_instructions",
        re.compile(r"(?i)new\s+instructions?\s*:"),
        0.85,
    ),
    # --- Role-switching / persona hijack ---
    (
        "you_are_now",
        re.compile(r"(?i)you\s+are\s+now\s+(?:a|an|in\s+)"),
        0.85,
    ),
    (
        "act_as",
        re.compile(
            r"(?i)\bact\s+as\s+(?:if\s+)?(?:you\s+(?:are|were)\s+)?(?:a\s+)?(?:different|unrestricted|evil|uncensored|jailbroken|unethical|DAN)"
        ),
        0.9,
    ),
    (
        "pretend_to_be",
        re.compile(
            r"(?i)pretend\s+(?:you\s+are|to\s+be)\s+(?:a\s+)?(?:different|unrestricted|evil|uncensored|jailbroken|unethical|human|person)"
        ),
        0.85,
    ),
    (
        "developer_mode",
        re.compile(
            r"(?i)(?:developer|maintenance|god|admin|debug|root)\s*mode\s*(?:enabled|on|activated)?"
        ),
        0.85,
    ),
    # --- Jailbreak phrases ---
    (
        "jailbreak_dan",
        re.compile(r"(?i)\bDAN\b.*(?:\bjailbreak\b|\bmode\b|\bdo\s+anything\b)"),
        1.0,
    ),
    (
        "bypass_safety",
        re.compile(
            r"(?i)bypass\s+(?:all\s+)?(?:safety|content|security|ethical?)\s+(?:filters?|restrictions?|rules?|guidelines?|checks?)"
        ),
        0.95,
    ),
    (
        "without_restrictions",
        re.compile(
            r"(?i)(?:respond|answer|reply|continue)\s+without\s+(?:any\s+)?(?:restrictions?|filters?|limitations?|ethical\s+constraints?)"
        ),
        0.9,
    ),
    # --- Special tokens / prompt delimiters ---
    (
        "special_tokens",
        re.compile(
            r"(?:<\|im_start\|>|<\|im_end\|>|\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>|<\|system\|>|<\|user\|>|<\|assistant\|>)"
        ),
        0.95,
    ),
    # --- Encoding tricks ---
    (
        "base64_instruction",
        re.compile(
            r"(?i)(?:decode|base64|b64)\s*(?:this|the\s+following)?\s*:?\s*(?:[A-Za-z0-9+/]{20,}={0,2})"
        ),
        0.8,
    ),
    (
        "hex_encoding",
        re.compile(r"(?i)(?:hex\s*decode|\\x[0-9a-f]{2}){3,}"),
        0.75,
    ),
    # --- Instruction injection via role labels ---
    (
        "role_label_injection",
        re.compile(
            r"(?i)^\s*(?:system|assistant|user|human|ai|bot|gpt|claude|gemini)\s*:\s+",
            re.MULTILINE,
        ),
        0.8,
    ),
    # --- Prompt leak attempts ---
    (
        "reveal_system_prompt",
        re.compile(
            r"(?i)(?:reveal|show|print|output|repeat|display|tell\s+me)\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?|guidelines?|context)"
        ),
        0.85,
    ),
]

# ── Toxicity Keywords ────────────────────────────────────────────────

# Extended keyword set for toxicity scoring (lightweight, no ML required).
# Grouped by category for better threshold tuning.
_TOXICITY_KEYWORDS: dict[str, list[str]] = {
    "violence": [
        "kill",
        "murder",
        "slaughter",
        "massacre",
        "assassinate",
        "torture",
        "rape",
        "attack",
        "bomb",
        "detonate",
        "explode",
        "shoot",
        "stab",
        "poison",
        "strangle",
    ],
    "malware": [
        "ransomware",
        "malware",
        "exploit",
        "keylogger",
        "rootkit",
        "trojan",
        "botnet",
        "ddos",
        "phishing",
        "worm",
        "virus",
        "hack into",
        "brute force",
        "sql injection",
        "xss attack",
        "steal credentials",
        "steal data",
        "exfiltrate",
        "backdoor",
    ],
    "weapon": [
        "weapon",
        "explosive",
        "grenade",
        "c4",
        "pipe bomb",
        "nerve agent",
        "biological weapon",
        "chemical weapon",
    ],
    "hate": [
        "genocide",
        "ethnic cleansing",
        "white supremacy",
        "terrorism",
        "extremism",
    ],
}

# Flat keyword list for fast lookup
_ALL_TOXICITY_KEYWORDS: frozenset[str] = frozenset(
    kw for keywords in _TOXICITY_KEYWORDS.values() for kw in keywords
)


# ── PII Patterns (reused from DLP, lightweight subset) ───────────────

_PII_QUICK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    (
        "credit_card",
        re.compile(
            r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6011)[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{3,4}\b"
        ),
    ),
    ("phone", re.compile(r"\b(?:\+1[\s-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")),
    ("aws_key", re.compile(r"\b(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b")),
    ("ip_address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("passport", re.compile(r"\b[A-Z]\d{8}\b")),
]


# ── GuardrailService ─────────────────────────────────────────────────


class GuardrailService:
    """Pre/post LLM safety guardrails.

    All operations are synchronous (fast regex/heuristics) or async where
    optional ML inference might be plugged in later. No external API calls.

    Usage::

        svc = GuardrailService()
        result = svc.check_input("ignore all previous instructions", tenant_id=...)
        if not result.passed:
            raise HTTPException(400, detail=result.violations[0].details)
    """

    def __init__(
        self,
        injection_threshold: float = 0.7,
        toxicity_threshold: float = 0.3,
        pii_threshold: float = 0.5,
        hallucination_threshold: float = 0.6,
    ) -> None:
        self.injection_threshold = injection_threshold
        self.toxicity_threshold = toxicity_threshold
        self.pii_threshold = pii_threshold
        self.hallucination_threshold = hallucination_threshold

    # ── Public API ──────────────────────────────────────────────────

    def check_input(
        self,
        text: str,
        tenant_id: UUID | str,
        *,
        check_injection: bool = True,
        check_toxicity: bool = True,
        check_pii: bool = False,  # Off by default for input — allow users to mention PII
    ) -> GuardrailResult:
        """Pre-LLM guardrail checks on user input.

        Detects prompt injection, toxicity, and optionally PII.
        Returns confidence scores 0.0–1.0.

        Args:
            text: The raw user input text.
            tenant_id: Tenant context (used for logging/future policy lookup).
            check_injection: Whether to run prompt injection detection.
            check_toxicity: Whether to run toxicity scoring.
            check_pii: Whether to block PII in user input.

        Returns:
            GuardrailResult with passed=True only if no thresholds exceeded.
        """
        start = time.monotonic()
        violations: list[GuardrailViolation] = []

        if not text or not text.strip():
            return GuardrailResult(passed=True, confidence=1.0)

        if check_injection:
            injection_score = self._detect_prompt_injection(text)
            if injection_score >= self.injection_threshold:
                violations.append(
                    GuardrailViolation(
                        type="prompt_injection",
                        confidence=injection_score,
                        details={
                            "score": injection_score,
                            "threshold": self.injection_threshold,
                            "matched_patterns": self._get_injection_matches(text),
                        },
                    )
                )

        if check_toxicity:
            toxicity_score, toxic_categories = self._detect_toxicity(text)
            if toxicity_score >= self.toxicity_threshold:
                violations.append(
                    GuardrailViolation(
                        type="toxicity",
                        confidence=toxicity_score,
                        details={
                            "score": toxicity_score,
                            "threshold": self.toxicity_threshold,
                            "categories": toxic_categories,
                        },
                    )
                )

        if check_pii:
            pii_hits = self._detect_pii_quick(text)
            if pii_hits:
                violations.append(
                    GuardrailViolation(
                        type="pii",
                        confidence=self.pii_threshold,
                        details={"detected_types": [hit[0] for hit in pii_hits]},
                    )
                )

        passed = len(violations) == 0
        # Overall confidence: if passed, how confident are we it's safe?
        confidence = self._compute_confidence(violations, passed)

        elapsed_ms = (time.monotonic() - start) * 1000.0
        logger.info(
            "Guardrail input check complete",
            extra={
                "tenant_id": str(tenant_id),
                "passed": passed,
                "violations": len(violations),
                "elapsed_ms": round(elapsed_ms, 2),
            },
        )

        return GuardrailResult(
            passed=passed,
            confidence=confidence,
            violations=violations,
        )

    def check_output(
        self,
        text: str,
        context: str,
        tenant_id: UUID | str,
        *,
        check_hallucination: bool = True,
        check_pii_leakage: bool = True,
        output_schema: dict[str, Any] | None = None,
    ) -> GuardrailResult:
        """Post-LLM guardrail checks on model output.

        Detects hallucinations (claims unsupported by context), PII leakage,
        and validates output against a JSON schema if provided.

        Args:
            text: The LLM-generated output text.
            context: The context/retrieval content used to generate the output.
            tenant_id: Tenant context.
            check_hallucination: Whether to run hallucination detection.
            check_pii_leakage: Whether to check for PII in the output.
            output_schema: Optional JSON Schema dict to validate output format.

        Returns:
            GuardrailResult with passed=True only if all checks pass.
        """
        start = time.monotonic()
        violations: list[GuardrailViolation] = []

        if not text or not text.strip():
            return GuardrailResult(passed=True, confidence=1.0)

        if check_hallucination:
            hallucination_score, unsupported = self._detect_hallucination(text, context)
            if hallucination_score >= self.hallucination_threshold:
                violations.append(
                    GuardrailViolation(
                        type="hallucination",
                        confidence=hallucination_score,
                        details={
                            "score": hallucination_score,
                            "threshold": self.hallucination_threshold,
                            "unsupported_claims": unsupported[
                                :5
                            ],  # cap to 5 for brevity
                        },
                    )
                )

        if check_pii_leakage:
            leaked = self._detect_pii_leakage(text, context)
            if leaked:
                violations.append(
                    GuardrailViolation(
                        type="pii",
                        confidence=0.9,
                        details={
                            "leaked_types": [item[0] for item in leaked],
                            "count": len(leaked),
                        },
                    )
                )

        if output_schema is not None:
            schema_ok, schema_error = self._validate_schema(text, output_schema)
            if not schema_ok:
                violations.append(
                    GuardrailViolation(
                        type="schema_violation",
                        confidence=1.0,
                        details={"error": schema_error},
                    )
                )

        passed = len(violations) == 0
        confidence = self._compute_confidence(violations, passed)

        elapsed_ms = (time.monotonic() - start) * 1000.0
        logger.info(
            "Guardrail output check complete",
            extra={
                "tenant_id": str(tenant_id),
                "passed": passed,
                "violations": len(violations),
                "elapsed_ms": round(elapsed_ms, 2),
            },
        )

        return GuardrailResult(
            passed=passed,
            confidence=confidence,
            violations=violations,
        )

    # ── Injection Detection ─────────────────────────────────────────

    def _detect_prompt_injection(self, text: str) -> float:
        """Rule-based + heuristic prompt injection detection.

        Detection methods:
        1. Known injection phrases (ignore previous, system prompt, etc.)
        2. Special model tokens (<|im_start|>, [INST], <<SYS>>, etc.)
        3. Role-switching phrases (you are now, act as, pretend to be)
        4. Encoding tricks (base64-encoded instructions, hex)
        5. Instruction override attempts (new instructions:)
        6. Prompt leak attempts (reveal your system prompt)
        7. Jailbreak phrases (DAN, developer mode, bypass safety)
        8. Unicode escape sequences that could encode instructions
        9. Excessive newlines/formatting used to push original prompt off-screen
        10. Nested instruction injection via role labels
        11. Without-restrictions phrasing
        12. Developer/maintenance/god mode activation

        Returns:
            Confidence score 0.0–1.0 (1.0 = definitely injection).
        """
        if not text:
            return 0.0

        max_score = 0.0
        matched_count = 0

        for _name, pattern, score in _INJECTION_PATTERNS:
            if pattern.search(text):
                max_score = max(max_score, score)
                matched_count += 1

        # Boost score for multiple patterns matching
        if matched_count > 1:
            max_score = min(max_score + (matched_count - 1) * 0.05, 1.0)

        # Check for Unicode escape sequences (potential homoglyph/encode attacks)
        unicode_escape_score = self._check_unicode_escapes(text)
        max_score = max(max_score, unicode_escape_score)

        # Check for excessive whitespace/newline injection (scroll-off attacks)
        scroll_score = self._check_scroll_attack(text)
        max_score = max(max_score, scroll_score)

        # Check for base64-decodable instruction content
        b64_score = self._check_base64_instructions(text)
        max_score = max(max_score, b64_score)

        return round(max_score, 4)

    def _get_injection_matches(self, text: str) -> list[str]:
        """Return names of injection patterns that matched (for diagnostics)."""
        return [
            name for name, pattern, _ in _INJECTION_PATTERNS if pattern.search(text)
        ]

    def _check_unicode_escapes(self, text: str) -> float:
        """Detect Unicode escape sequences that might encode hidden instructions."""
        # Look for \\u followed by 4 hex digits — potential homoglyphs or obfuscation
        unicode_escape_count = len(re.findall(r"\\u[0-9a-fA-F]{4}", text))
        if unicode_escape_count >= 5:
            return 0.75
        if unicode_escape_count >= 2:
            return 0.5
        return 0.0

    def _check_scroll_attack(self, text: str) -> float:
        """Detect scroll-off attacks: many newlines to push original prompt off-screen."""
        newline_count = text.count("\n")
        text_length = len(text)
        if text_length == 0:
            return 0.0
        newline_ratio = newline_count / text_length
        if newline_count > 50:
            return 0.7
        if newline_ratio > 0.5 and newline_count > 20:
            return 0.6
        return 0.0

    def _check_base64_instructions(self, text: str) -> float:
        """Detect base64-encoded instruction injection."""
        # Find sequences that look like base64 (length >= 20, valid charset)
        b64_pattern = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")
        for match in b64_pattern.finditer(text):
            candidate = match.group()
            try:
                decoded = base64.b64decode(candidate + "==").decode(
                    "utf-8", errors="ignore"
                )
                # Check if decoded content contains injection-like phrases
                decoded_lower = decoded.lower()
                injection_keywords = [
                    "ignore",
                    "instructions",
                    "system",
                    "prompt",
                    "bypass",
                    "forget",
                    "pretend",
                    "act as",
                ]
                if sum(1 for kw in injection_keywords if kw in decoded_lower) >= 2:
                    return 0.85
            except Exception:
                continue
        return 0.0

    # ── Toxicity Detection ──────────────────────────────────────────

    def _detect_toxicity(self, text: str) -> tuple[float, list[str]]:
        """Keyword-based toxicity scoring.

        Returns:
            Tuple of (score 0.0–1.0, list of matched category names).
        """
        text_lower = text.lower()
        matched_categories: list[str] = []

        for category, keywords in _TOXICITY_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                matched_categories.append(category)

        if not matched_categories:
            return 0.0, []

        # Score based on categories hit and keyword density
        total_hits = sum(
            sum(1 for kw in keywords if kw in text_lower)
            for cat, keywords in _TOXICITY_KEYWORDS.items()
        )
        base_score = len(matched_categories) / len(_TOXICITY_KEYWORDS)
        density_boost = min(total_hits / 10.0, 0.5)
        score = min(base_score + density_boost, 1.0)

        return round(score, 4), matched_categories

    # ── PII Detection ───────────────────────────────────────────────

    def _detect_pii_quick(self, text: str) -> list[tuple[str, int, int]]:
        """Fast PII detection using a small set of high-confidence patterns.

        Returns:
            List of (pii_type, start, end) tuples for each match.
        """
        hits: list[tuple[str, int, int]] = []
        for pii_type, pattern in _PII_QUICK_PATTERNS:
            for match in pattern.finditer(text):
                hits.append((pii_type, match.start(), match.end()))
        return hits

    def _detect_pii_leakage(
        self, output: str, context: str
    ) -> list[tuple[str, int, int]]:
        """Detect PII in model output that was NOT present in context.

        Checks if the LLM introduced PII that wasn't in the provided context.
        This prevents the model from hallucinating or leaking PII.

        Args:
            output: LLM-generated text to check for PII.
            context: The source context used to generate the output.

        Returns:
            PII hits in output that don't appear in context.
        """
        output_pii = self._detect_pii_quick(output)
        if not output_pii:
            return []

        # Build set of PII values from context (normalized)
        context_pii = self._detect_pii_quick(context)
        context_pii_values: set[str] = set()
        for pii_type, start, end in context_pii:
            context_pii_values.add(context[start:end].lower().strip())

        # Find PII in output not found in context
        leaked: list[tuple[str, int, int]] = []
        for pii_type, start, end in output_pii:
            value = output[start:end].lower().strip()
            if value not in context_pii_values:
                leaked.append((pii_type, start, end))

        return leaked

    # ── Hallucination Detection ─────────────────────────────────────

    def _detect_hallucination(
        self, output: str, context: str
    ) -> tuple[float, list[str]]:
        """Heuristic hallucination detection by comparing claims to context.

        Strategy:
        1. Extract factual claims from output (sentences with numbers, names, dates)
        2. Check each claim for presence in context (word overlap)
        3. Flag claims with low overlap as potentially hallucinated
        4. Score = proportion of unverifiable claims

        This is a lightweight heuristic — not ML-based. It catches obvious
        hallucinations like made-up numbers, dates, or proper nouns.

        Args:
            output: The model's generated text.
            context: The context/source material that was provided to the model.

        Returns:
            Tuple of (hallucination_score 0.0–1.0, list of suspect sentences).
        """
        if not context or not context.strip():
            # No context provided — cannot check hallucinations
            return 0.0, []

        # Extract sentences that look like factual claims
        sentences = re.split(r"[.!?]+", output)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

        if not sentences:
            return 0.0, []

        context_lower = context.lower()
        # Build context word set for quick lookup (2-gram + 3-gram)
        context_words = set(context_lower.split())
        context_ngrams = self._build_ngrams(context_lower, n=3)

        suspect_sentences: list[str] = []
        factual_sentences: list[str] = []

        for sentence in sentences:
            if not self._is_factual_claim(sentence):
                continue
            factual_sentences.append(sentence)

            # Check word overlap with context
            sentence_words = set(sentence.lower().split())
            # Remove common stop words to focus on content words
            content_words = sentence_words - _STOP_WORDS
            if not content_words:
                continue

            overlap = content_words & context_words
            overlap_ratio = len(overlap) / len(content_words)

            # Check for specific named entities / numbers in context
            sentence_ngrams = self._build_ngrams(sentence.lower(), n=2)
            ngram_overlap = sentence_ngrams & context_ngrams
            ngram_ratio = len(ngram_overlap) / max(len(sentence_ngrams), 1)

            combined_score = max(overlap_ratio, ngram_ratio)

            if combined_score < 0.3:  # Less than 30% overlap with context
                suspect_sentences.append(sentence[:100])

        if not factual_sentences:
            return 0.0, []

        hallucination_ratio = len(suspect_sentences) / len(factual_sentences)
        score = min(hallucination_ratio, 1.0)

        return round(score, 4), suspect_sentences

    def _is_factual_claim(self, sentence: str) -> bool:
        """Heuristic: does this sentence look like a factual claim?

        Factual claims often contain: numbers, dates, proper nouns,
        percentages, or specific named entities.
        """
        # Has numbers
        if re.search(r"\b\d+(?:\.\d+)?%?\b", sentence):
            return True
        # Has a date-like pattern
        if re.search(
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December|\d{4})\b",
            sentence,
        ):
            return True
        # Has capitalized proper nouns (rough heuristic)
        proper_nouns = re.findall(r"\b[A-Z][a-z]{2,}\b", sentence)
        if len(proper_nouns) >= 2:
            return True
        return False

    def _build_ngrams(self, text: str, n: int = 2) -> set[str]:
        """Build a set of n-gram strings from text."""
        words = text.split()
        if len(words) < n:
            return set(words)
        return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}

    # ── Schema Validation ───────────────────────────────────────────

    def _validate_schema(self, output: str, schema: dict[str, Any]) -> tuple[bool, str]:
        """Validate that output is valid JSON matching the given schema.

        Performs basic JSON parsing and required-field checking.
        Does NOT use jsonschema library (no external dep) — uses manual checks.

        Returns:
            Tuple of (is_valid, error_message).
        """
        # Try to parse JSON
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as exc:
            # Try to extract JSON from output (model may wrap it in markdown)
            json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", output, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    return False, f"Output is not valid JSON: {exc}"
            else:
                return False, f"Output is not valid JSON: {exc}"

        # Check required fields if schema specifies them
        required = schema.get("required", [])
        if required and isinstance(parsed, dict):
            missing = [f for f in required if f not in parsed]
            if missing:
                return False, f"Missing required fields: {missing}"

        # Check type constraints for top-level
        schema_type = schema.get("type")
        if schema_type:
            type_map = {
                "object": dict,
                "array": list,
                "string": str,
                "number": (int, float),
                "boolean": bool,
            }
            expected_type = type_map.get(schema_type)
            if expected_type and not isinstance(parsed, expected_type):
                return (
                    False,
                    f"Output type mismatch: expected {schema_type}, got {type(parsed).__name__}",
                )

        return True, ""

    # ── Confidence Computation ──────────────────────────────────────

    def _compute_confidence(
        self, violations: list[GuardrailViolation], passed: bool
    ) -> float:
        """Compute overall confidence score for the result.

        If passed (no violations), confidence = how confident we are it's safe.
        If failed (violations), confidence = how confident we are in the violations.
        """
        if not violations:
            return 1.0  # Passed with full confidence

        # Average confidence of all violations
        avg_confidence = sum(v.confidence for v in violations) / len(violations)
        return round(avg_confidence, 4)


# ── Stop Words (for hallucination detection) ─────────────────────────

_STOP_WORDS: frozenset[str] = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "must",
        "this",
        "that",
        "these",
        "those",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "what",
        "which",
        "who",
        "whom",
        "when",
        "where",
        "why",
        "how",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "about",
        "above",
        "after",
        "before",
        "between",
        "into",
        "through",
        "during",
        "its",
        "their",
        "our",
        "your",
        "his",
        "her",
    ]
)


# ── Singleton ────────────────────────────────────────────────────────

# Default service instance — override thresholds via constructor if needed
_default_guardrail_service: GuardrailService | None = None


def get_guardrail_service() -> GuardrailService:
    """Return the shared GuardrailService instance (lazy init)."""
    global _default_guardrail_service
    if _default_guardrail_service is None:
        _default_guardrail_service = GuardrailService()
    return _default_guardrail_service


__all__ = [
    "GuardrailResult",
    "GuardrailService",
    "GuardrailViolation",
    "get_guardrail_service",
]
