"""Structured-output node executor — JSON-mode LLM call constrained to a schema.

Phase 3 / WS9 — Executor Workstream 2.

The node receives a prompt + a JSON Schema (draft-7 / 2020-12 compatible) and
returns an output dict that has been validated against the schema. Promoted
from STUB to BETA: a real ``call_llm`` wrapper backs the executor, with the
same stub-mode discipline as ``llmNode`` and ``embeddingNode`` so tests stay
deterministic.

Stub mode (``LLM_STUB_MODE=true``)
----------------------------------
``call_llm`` returns a synthetic ``[STUB] …`` content string in stub mode,
which is not a JSON document. To preserve schema-valid output without making
a real provider call, the executor synthesises a minimal valid object by
walking the schema:

  - ``type: object`` → recurse on each ``required`` property; missing
    optional properties are omitted.
  - Primitives use the schema's ``default`` if present, else type-appropriate
    placeholders ("stub" / 0 / 0.0 / False / [] / {}).
  - Synthesis is deterministic: identical (prompt, schema) inputs always
    yield identical objects (the placeholder values are constants, no PRNG
    is involved).

Real mode
---------
The executor builds a "return JSON matching this schema" prompt, calls
``call_llm`` with the user's model + prompt, parses the response as JSON, and
validates it against the schema via ``jsonschema.validate``. Validation
failures surface as ``status="failed"`` with ``error_code="schema_validation_failed"``
so the dispatcher's RetryPolicy can classify them as non-retryable.

Output shape (success)
----------------------

    {
        "output": <validated dict>,
        "model": str,            # provider model id (with -stub suffix in stub mode)
        "schema": <schema dict>,  # echoed for downstream debugging
        "token_usage": {"prompt": int, "completion": int, "total": int},
        "cost_usd": float | None,
        "latency_ms": float,
        "_stub": bool,            # only set when LLM_STUB_MODE=true
    }

Caveats (BETA gap)
------------------
  - One-shot only — multi-turn refinement / re-asking on validation failure
    is not implemented.
  - Streaming is not supported. The node always waits for the full response
    before validating.
  - ``response_format={"type": "json_object"}`` is not yet wired into
    ``call_llm`` — instead the prompt is augmented with an explicit JSON
    instruction. Provider-side JSON mode is a Phase 4 enhancement.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register

logger = logging.getLogger(__name__)


_DEFAULT_MODEL = "gpt-4o-mini"


def _is_stub_mode() -> bool:
    return os.getenv("LLM_STUB_MODE", "").lower() == "true"


# ---------------------------------------------------------------------------
# Stub-mode schema synthesis
# ---------------------------------------------------------------------------


def _canonical_schema_hash(prompt: str, schema: dict) -> str:
    """sha256 over (prompt + canonical JSON of schema).

    Used only for trace metadata in stub mode — the synthesised object is
    deterministic via constants, not via a hash-seeded PRNG. The hash is
    surfaced so callers debugging stub determinism can confirm two calls
    operated on the same inputs.
    """
    blob = f"{prompt}\x1e{json.dumps(schema, sort_keys=True, default=str)}".encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def _synthesise_from_schema(schema: Any) -> Any:
    """Walk *schema* and return a minimal value that satisfies it.

    Honours ``default`` first (if present at any node), then falls through to
    type-appropriate placeholders. Object nodes recurse only on the
    ``required`` list — optional properties are omitted to keep the
    synthesised object as small as possible.

    Unknown / missing types degrade to ``None`` so callers can detect a
    schema that the synthesiser cannot interpret.
    """
    if not isinstance(schema, dict):
        return None

    # Explicit default wins regardless of type.
    if "default" in schema:
        return schema["default"]

    # ``const`` — pin to the constant.
    if "const" in schema:
        return schema["const"]

    # ``enum`` — first value is the cheapest valid pick.
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]

    # Schema combinators: pick the simplest branch.
    for combinator in ("anyOf", "oneOf", "allOf"):
        branches = schema.get(combinator)
        if isinstance(branches, list) and branches:
            # ``allOf`` is conservative: synthesise the first branch and
            # trust it. A real implementation would intersect schemas.
            return _synthesise_from_schema(branches[0])

    schema_type = schema.get("type")

    # ``type`` may be a list (e.g. ["string", "null"]). Pick the first
    # non-null type to keep the output non-trivial.
    if isinstance(schema_type, list):
        for t in schema_type:
            if t != "null":
                schema_type = t
                break
        else:
            schema_type = "null"

    if schema_type == "object":
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        out: dict[str, Any] = {}
        for prop in required:
            if prop in properties:
                out[prop] = _synthesise_from_schema(properties[prop])
            else:
                # Required key without a defined property — best-effort
                # placeholder.
                out[prop] = "stub"
        return out

    if schema_type == "array":
        items = schema.get("items")
        min_items = int(schema.get("minItems") or 0)
        if min_items <= 0:
            return []
        # minItems > 0 — synthesise the minimum count of placeholder items.
        single = _synthesise_from_schema(items) if isinstance(items, dict) else "stub"
        return [single for _ in range(min_items)]

    if schema_type == "string":
        return "stub"
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0.0
    if schema_type == "boolean":
        return False
    if schema_type == "null":
        return None

    # Untyped schema — empty object is a safe minimum.
    return {}


# ---------------------------------------------------------------------------
# Real-mode validation helpers
# ---------------------------------------------------------------------------


def _validate_against_schema(payload: Any, schema: dict) -> str | None:
    """Validate *payload* against *schema*. Return error string on failure.

    Lazy-imports ``jsonschema`` so the module is importable in environments
    that have not yet installed the library. If the import fails we surface
    a clear actionable error rather than silently passing.
    """
    try:
        import jsonschema  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover — exercised only when dep missing
        return (
            "jsonschema package is required for real-mode structured output "
            f"validation but is not installed: {exc}"
        )

    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        # The validator's message includes the path + reason — keep it.
        return f"{exc.message} (path: {list(exc.absolute_path)})"
    except jsonschema.SchemaError as exc:
        return f"invalid schema: {exc.message}"

    return None


def _parse_json_content(content: str) -> tuple[Any | None, str | None]:
    """Parse *content* as JSON. Return ``(value, None)`` or ``(None, err)``.

    Tolerates a small amount of provider preamble — strips Markdown code
    fences and leading/trailing whitespace before parsing. Anything more
    complex is the provider's fault, surfaced as an explicit error.
    """
    if not isinstance(content, str):
        return None, "LLM response content was not a string"

    text = content.strip()

    # Strip Markdown fences (```json ... ``` or ``` ... ```).
    if text.startswith("```"):
        # Drop opening fence + optional language tag.
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        # Drop trailing fence.
        if text.rstrip().endswith("```"):
            text = text.rstrip()[: -len("```")]

    text = text.strip()

    if not text:
        return None, "LLM response was empty"

    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"LLM response is not valid JSON: {exc}"


def _build_json_prompt(prompt: str, schema: dict) -> str:
    """Augment *prompt* with explicit JSON-mode instructions.

    Provider-side ``response_format={"type": "json_object"}`` is the long-term
    solution — until then we instruct the model to emit JSON only.
    """
    return (
        f"{prompt}\n\n"
        "Respond ONLY with a JSON object that conforms to this JSON Schema. "
        "Do not include any prose, Markdown, or code fences.\n"
        f"JSON Schema:\n{json.dumps(schema)}"
    )


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


@register("structuredOutputNode")
class StructuredOutputNodeExecutor(NodeExecutor):
    """Execute a structuredOutputNode: LLM call + JSON-schema validation."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        from app.langgraph.llm import call_llm  # noqa: PLC0415

        config = ctx.config

        # ── Required: schema ──────────────────────────────────────────
        schema = config.get("schema")
        if not isinstance(schema, dict) or not schema:
            return NodeResult(
                status="failed",
                error="ValueError: structuredOutputNode requires non-empty 'schema' (JSON Schema dict)",
                output={"error_code": "missing_schema"},
            )

        # ── Required: prompt ──────────────────────────────────────────
        prompt = (
            config.get("prompt")
            or config.get("userPrompt")
            or config.get("user_prompt")
        )
        if not isinstance(prompt, str) or not prompt.strip():
            # Fall back to upstream inputs if exactly one upstream produced
            # a string output — mirrors the embeddingNode resolution rule.
            inputs = ctx.inputs or {}
            if len(inputs) == 1:
                only = next(iter(inputs.values()))
                if isinstance(only, str) and only.strip():
                    prompt = only
            if not isinstance(prompt, str) or not prompt.strip():
                return NodeResult(
                    status="failed",
                    error="ValueError: structuredOutputNode requires non-empty 'prompt' in config or upstream inputs",
                    output={"error_code": "missing_prompt"},
                )

        # Inject upstream outputs into prompt placeholders ({step_id}).
        for step_id, step_out in (ctx.inputs or {}).items():
            prompt = prompt.replace(f"{{{step_id}}}", str(step_out))

        model: str = config.get("model") or _DEFAULT_MODEL
        system: str | None = config.get("systemPrompt") or config.get("system_prompt")
        max_tokens: int = int(config.get("maxTokens") or config.get("max_tokens") or 1024)
        temperature: float = float(config.get("temperature") or 0.7)

        # ── Stub mode: synthesise a schema-valid object ────────────────
        if _is_stub_mode():
            synthesised = _synthesise_from_schema(schema)
            schema_hash = _canonical_schema_hash(prompt, schema)
            # Make a stub-flavoured call_llm so token/cost/latency are
            # populated consistently with embeddingNode / llmNode.
            response = await call_llm(
                prompt,
                model=model,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            output: dict[str, Any] = {
                "output": synthesised,
                "model": response.model_used,
                "schema": schema,
                "schema_hash": schema_hash,
                "token_usage": {
                    "prompt": response.prompt_tokens,
                    "completion": response.completion_tokens,
                    "total": response.total_tokens,
                },
                "cost_usd": response.cost_usd,
                "latency_ms": response.latency_ms,
                "_stub": True,
            }
            return NodeResult(
                status="completed",
                output=output,
                token_usage={
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "total_tokens": response.total_tokens,
                },
                cost_usd=response.cost_usd,
            )

        # ── Real mode: call_llm + jsonschema.validate ─────────────────
        json_prompt = _build_json_prompt(prompt, schema)
        try:
            response = await call_llm(
                json_prompt,
                model=model,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("structuredOutputNode.call_llm_error", exc_info=True)
            # Preserve exception class name so RetryPolicy can classify it.
            return NodeResult(
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )

        parsed, parse_err = _parse_json_content(response.content)
        if parse_err is not None:
            return NodeResult(
                status="failed",
                error=f"schema_validation_failed: {parse_err}",
                output={
                    "error_code": "schema_validation_failed",
                    "raw_content": response.content,
                },
            )

        validation_err = _validate_against_schema(parsed, schema)
        if validation_err is not None:
            return NodeResult(
                status="failed",
                error=f"schema_validation_failed: {validation_err}",
                output={
                    "error_code": "schema_validation_failed",
                    "raw_content": response.content,
                    "parsed": parsed,
                },
            )

        output = {
            "output": parsed,
            "model": response.model_used,
            "schema": schema,
            "token_usage": {
                "prompt": response.prompt_tokens,
                "completion": response.completion_tokens,
                "total": response.total_tokens,
            },
            "cost_usd": response.cost_usd,
            "latency_ms": response.latency_ms,
        }
        return NodeResult(
            status="completed",
            output=output,
            token_usage={
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "total_tokens": response.total_tokens,
            },
            cost_usd=response.cost_usd,
        )
