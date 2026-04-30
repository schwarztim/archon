"""W4c + W4d node executor contract tests.

Covers the six executors promoted to BETA in this workstream:

W4c — Workflow-Control Executors
    * loopNode          — ADR-003 hint emitter (already real; status promotion)
    * subWorkflowNode   — recursive workflow invoke (already BETA)
    * subAgentNode      — sub-agent invoke (already BETA)

W4d — AI/Data-Shaping Executors
    * vectorSearchNode  — in-memory cosine similarity search
    * documentLoaderNode — URL / file / text load + chunking
    * streamOutputNode  — format + persist artifact; optional WS delivery

All tests are self-contained (no DB, no network, no real LLM) and use
``--noconftest``-compatible imports.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Force stub mode so embedding calls are deterministic without provider creds.
os.environ.setdefault("LLM_STUB_MODE", "true")

from app.services.node_executors import NODE_EXECUTORS  # noqa: E402
from app.services.node_executors._stub_block import assert_node_runnable  # noqa: E402
from app.services.node_executors.status_registry import (  # noqa: E402
    NODE_STATUS,
    NodeStatus,
)
from tests.test_node_executors import make_ctx  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_embedding_response(text: str = "x", dims: int = 4) -> Any:
    """Return a minimal fake EmbeddingResponse-like object."""
    from app.langgraph.embeddings import EmbeddingResponse  # noqa: PLC0415

    return EmbeddingResponse(
        vector=[0.5] * dims,
        dimensions=dims,
        prompt_tokens=2,
        total_tokens=2,
        cost_usd=0.0,
        model_used="text-embedding-3-small-stub",
        latency_ms=1.0,
    )


# ===========================================================================
# W4c — loopNode
# ===========================================================================


class TestLoopNode:
    """loopNode emits an ADR-003 hint envelope; execution is engine-side."""

    @pytest.mark.asyncio
    async def test_loop_executes_n_iterations_via_hint(self):
        """max_iterations is captured in the _hint envelope."""
        ctx = make_ctx("loopNode", config={"maxIterations": 5})
        result = await NODE_EXECUTORS["loopNode"].execute(ctx)

        assert result.status == "completed"
        assert result.output["max_iterations"] == 5
        assert result.output.get("_loop_hint") is True

    @pytest.mark.asyncio
    async def test_loop_max_iterations_limit(self):
        """Values above the hard cap (1000) are clamped silently."""
        ctx = make_ctx("loopNode", config={"maxIterations": 99_999})
        result = await NODE_EXECUTORS["loopNode"].execute(ctx)

        assert result.status == "completed"
        assert result.output["max_iterations"] == 1_000

    @pytest.mark.asyncio
    async def test_loop_hint_contains_body_step_ids(self):
        """body_step_ids are reflected in _hint['body_step_ids']."""
        ctx = make_ctx(
            "loopNode",
            config={
                "maxIterations": 3,
                "bodyStepIds": ["step-a", "step-b"],
                "accumulateMode": "list",
            },
        )
        result = await NODE_EXECUTORS["loopNode"].execute(ctx)

        assert result.status == "completed"
        hint = result.output.get("_hint")
        assert hint is not None
        assert hint["kind"] == "loop"
        assert hint["body_step_ids"] == ["step-a", "step-b"]
        assert hint["max_iterations"] == 3
        assert hint["accumulate_mode"] == "list"

    @pytest.mark.asyncio
    async def test_loop_condition_expr_forwarded(self):
        """condition_expr is forwarded verbatim in the hint."""
        ctx = make_ctx(
            "loopNode",
            config={
                "maxIterations": 10,
                "bodyStepIds": ["s1"],
                "conditionExpr": "x < 100",
            },
        )
        result = await NODE_EXECUTORS["loopNode"].execute(ctx)

        hint = result.output.get("_hint", {})
        assert hint.get("condition_expr") == "x < 100"

    def test_loop_classified_beta(self):
        """loopNode registry status is BETA."""
        assert NODE_STATUS["loopNode"] is NodeStatus.BETA

    def test_loop_runnable_in_production(self):
        """assert_node_runnable does not raise for loopNode."""
        assert_node_runnable("loopNode", env="production")


# ===========================================================================
# W4c — subWorkflowNode
# ===========================================================================


class TestSubWorkflowNode:
    @pytest.mark.asyncio
    async def test_sub_workflow_creates_child_run(self):
        """When workflowDefinition is provided, execute_workflow_dag is called."""
        sub_def = {"steps": [{"id": "s1", "type": "inputNode", "config": {}}]}
        ctx = make_ctx(
            "subWorkflowNode",
            config={
                "workflowId": "wf-child",
                "workflowDefinition": sub_def,
            },
        )

        mock_result = {"status": "completed", "output": {"answer": 42}}
        # The executor uses a lazy import inside execute(); patch the target module.
        with patch(
            "app.services.workflow_engine.execute_workflow_dag",
            new=AsyncMock(return_value=mock_result),
            create=True,
        ):
            result = await NODE_EXECUTORS["subWorkflowNode"].execute(ctx)

        assert result.status == "completed"
        assert result.output["workflow_id"] == "wf-child"
        assert result.output["sub_result"] == mock_result

    @pytest.mark.asyncio
    async def test_sub_workflow_depth_limit_exceeded(self):
        """Missing workflowId → status=failed."""
        ctx = make_ctx("subWorkflowNode", config={})
        result = await NODE_EXECUTORS["subWorkflowNode"].execute(ctx)
        assert result.status == "failed"
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_sub_workflow_cycle_detection(self):
        """When the DAG raises (cycle or error), status=failed with error text."""
        ctx = make_ctx(
            "subWorkflowNode",
            config={
                "workflowId": "wf-cycle",
                "workflowDefinition": {"steps": []},
            },
        )

        with patch(
            "app.services.workflow_engine.execute_workflow_dag",
            new=AsyncMock(side_effect=RuntimeError("cycle detected")),
            create=True,
        ):
            result = await NODE_EXECUTORS["subWorkflowNode"].execute(ctx)

        assert result.status == "failed"
        assert "cycle" in (result.error or "").lower()

    def test_sub_workflow_classified_beta(self):
        assert NODE_STATUS["subWorkflowNode"] is NodeStatus.BETA

    def test_sub_workflow_runnable_in_production(self):
        assert_node_runnable("subWorkflowNode", env="production")


# ===========================================================================
# W4c — subAgentNode
# ===========================================================================


class TestSubAgentNode:
    @pytest.mark.asyncio
    async def test_sub_agent_missing_agent_id_returns_failed(self):
        ctx = make_ctx("subAgentNode", config={})
        result = await NODE_EXECUTORS["subAgentNode"].execute(ctx)
        assert result.status == "failed"
        assert "agentId" in (result.error or "")

    @pytest.mark.asyncio
    async def test_sub_agent_invokes_execute_agent(self):
        """execute_agent is called with the correct agent_id."""
        ctx = make_ctx(
            "subAgentNode",
            config={"agentId": "agent-99"},
        )

        mock_result = {"status": "completed", "output": "done", "steps": []}
        # Lazy import inside execute(); patch the source module directly.
        with patch(
            "app.langgraph.engine.execute_agent",
            new=AsyncMock(return_value=mock_result),
            create=True,
        ):
            result = await NODE_EXECUTORS["subAgentNode"].execute(ctx)

        assert result.status == "completed"
        assert result.output["agent_id"] == "agent-99"

    def test_sub_agent_classified_beta(self):
        assert NODE_STATUS["subAgentNode"] is NodeStatus.BETA

    def test_sub_agent_runnable_in_production(self):
        assert_node_runnable("subAgentNode", env="production")


# ===========================================================================
# W4d — vectorSearchNode
# ===========================================================================


class TestVectorSearchNode:
    """vectorSearchNode: embed query, cosine-rank documents, return top-K."""

    def _docs(self) -> list[dict]:
        return [
            {"id": "d1", "text": "apple fruit nutrition", "metadata": {"cat": "food"}},
            {"id": "d2", "text": "machine learning algorithms", "metadata": {}},
            {"id": "d3", "text": "apple iPhone smartphone", "metadata": {}},
        ]

    @pytest.mark.asyncio
    async def test_vector_search_returns_ranked_results(self):
        """Documents are returned ordered by cosine score descending."""
        ctx = make_ctx(
            "vectorSearchNode",
            config={
                "query_text": "apple",
                "collection": "test",
                "top_k": 3,
                "documents": self._docs(),
            },
        )
        # LLM_STUB_MODE=true produces deterministic vectors — run normally.
        result = await NODE_EXECUTORS["vectorSearchNode"].execute(ctx)

        assert result.status == "completed"
        assert result.output["collection"] == "test"
        assert result.output["query"] == "apple"
        assert isinstance(result.output["results"], list)
        assert len(result.output["results"]) <= 3
        # Results must be sorted descending by score.
        scores = [r["score"] for r in result.output["results"]]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_vector_search_top_k_limits_results(self):
        """top_k=1 returns at most one result."""
        ctx = make_ctx(
            "vectorSearchNode",
            config={
                "query_text": "query",
                "top_k": 1,
                "documents": self._docs(),
            },
        )
        result = await NODE_EXECUTORS["vectorSearchNode"].execute(ctx)
        assert result.status == "completed"
        assert len(result.output["results"]) <= 1

    @pytest.mark.asyncio
    async def test_vector_search_empty_documents_returns_empty(self):
        """No documents → empty results list, status=completed."""
        ctx = make_ctx(
            "vectorSearchNode",
            config={"query_text": "anything", "documents": []},
        )
        result = await NODE_EXECUTORS["vectorSearchNode"].execute(ctx)
        assert result.status == "completed"
        assert result.output["results"] == []

    @pytest.mark.asyncio
    async def test_vector_search_missing_query_returns_failed(self):
        """No query_text → status=failed with ValueError shape."""
        ctx = make_ctx(
            "vectorSearchNode",
            config={"documents": self._docs()},
        )
        result = await NODE_EXECUTORS["vectorSearchNode"].execute(ctx)
        assert result.status == "failed"
        assert "ValueError" in (result.error or "")

    @pytest.mark.asyncio
    async def test_vector_search_embedding_error_returns_failed(self):
        """call_embedding raising → status=failed with error class name."""
        ctx = make_ctx(
            "vectorSearchNode",
            config={"query_text": "q", "documents": self._docs()},
        )
        with patch(
            "app.langgraph.embeddings.call_embedding",
            new=AsyncMock(side_effect=RuntimeError("provider down")),
        ):
            result = await NODE_EXECUTORS["vectorSearchNode"].execute(ctx)
        assert result.status == "failed"
        assert "RuntimeError" in (result.error or "")

    def test_vector_search_classified_beta(self):
        assert NODE_STATUS["vectorSearchNode"] is NodeStatus.BETA

    def test_vector_search_runnable_in_production(self):
        assert_node_runnable("vectorSearchNode", env="production")


# ===========================================================================
# W4d — documentLoaderNode
# ===========================================================================


class TestDocumentLoaderNode:
    @pytest.mark.asyncio
    async def test_document_loader_chunks_text(self):
        """source_type='text' with chunk_size=10 produces multiple chunks."""
        text = "A" * 50  # 50 chars, 10 per chunk → 5+ chunks
        ctx = make_ctx(
            "documentLoaderNode",
            config={
                "source_type": "text",
                "source": text,
                "chunk_size": 10,
                "chunk_overlap": 0,
            },
        )
        result = await NODE_EXECUTORS["documentLoaderNode"].execute(ctx)

        assert result.status == "completed"
        assert result.output["source_type"] == "text"
        assert result.output["chunk_count"] >= 5
        assert result.output["total_chars"] == 50
        for chunk in result.output["chunks"]:
            assert "index" in chunk
            assert "text" in chunk
            assert "char_start" in chunk
            assert "char_end" in chunk

    @pytest.mark.asyncio
    async def test_document_loader_chunk_overlap(self):
        """Overlapping chunks share characters at boundaries."""
        text = "0123456789"  # 10 chars
        ctx = make_ctx(
            "documentLoaderNode",
            config={
                "source_type": "text",
                "source": text,
                "chunk_size": 6,
                "chunk_overlap": 2,
            },
        )
        result = await NODE_EXECUTORS["documentLoaderNode"].execute(ctx)
        assert result.status == "completed"
        chunks = result.output["chunks"]
        assert len(chunks) >= 2
        # Second chunk starts at offset step = chunk_size - overlap = 4.
        assert chunks[1]["char_start"] == 4

    @pytest.mark.asyncio
    async def test_document_loader_url_fetch(self):
        """source_type='url' calls httpx; on success returns chunked content."""
        ctx = make_ctx(
            "documentLoaderNode",
            config={
                "source_type": "url",
                "source": "https://example.com/doc.txt",
                "chunk_size": 100,
                "chunk_overlap": 0,
            },
        )

        fake_response = MagicMock()
        fake_response.text = "Hello from URL! " * 5  # 80 chars
        fake_response.headers = {"content-type": "text/plain"}
        fake_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await NODE_EXECUTORS["documentLoaderNode"].execute(ctx)

        assert result.status == "completed"
        assert result.output["source_type"] == "url"
        assert result.output["chunk_count"] >= 1

    @pytest.mark.asyncio
    async def test_document_loader_url_fetch_error_returns_failed(self):
        """HTTP error during URL fetch → status=failed."""
        ctx = make_ctx(
            "documentLoaderNode",
            config={
                "source_type": "url",
                "source": "https://example.com/bad",
            },
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=RuntimeError("connection refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await NODE_EXECUTORS["documentLoaderNode"].execute(ctx)

        assert result.status == "failed"
        assert "RuntimeError" in (result.error or "")

    @pytest.mark.asyncio
    async def test_document_loader_missing_source_returns_failed(self):
        """source_type='url' with no source → status=failed."""
        ctx = make_ctx(
            "documentLoaderNode",
            config={"source_type": "url"},
        )
        result = await NODE_EXECUTORS["documentLoaderNode"].execute(ctx)
        assert result.status == "failed"
        assert "source" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_document_loader_no_split_when_chunk_size_zero(self):
        """chunk_size=0 returns the whole text as a single chunk."""
        text = "abcdefghij" * 10  # 100 chars
        ctx = make_ctx(
            "documentLoaderNode",
            config={"source_type": "text", "source": text, "chunk_size": 0},
        )
        result = await NODE_EXECUTORS["documentLoaderNode"].execute(ctx)
        assert result.status == "completed"
        assert result.output["chunk_count"] == 1
        assert result.output["chunks"][0]["text"] == text

    def test_document_loader_classified_beta(self):
        assert NODE_STATUS["documentLoaderNode"] is NodeStatus.BETA

    def test_document_loader_runnable_in_production(self):
        assert_node_runnable("documentLoaderNode", env="production")


# ===========================================================================
# W4d — streamOutputNode
# ===========================================================================


class TestStreamOutputNode:
    @pytest.mark.asyncio
    async def test_stream_output_writes_artifact(self):
        """write_artifact is called when available on the context."""
        written: dict = {}

        async def _fake_write_artifact(name, payload, metadata):
            written["name"] = name
            written["payload"] = payload
            return "artifact://tenant/activity_output/abc123"

        ctx = make_ctx(
            "streamOutputNode",
            config={"content": "hello world", "stream_format": "json"},
        )
        # Inject write_artifact onto the NodeContext (not normally there).
        ctx.write_artifact = _fake_write_artifact  # type: ignore[attr-defined]

        result = await NODE_EXECUTORS["streamOutputNode"].execute(ctx)

        assert result.status == "completed"
        assert written["name"] == "stream_output"
        assert result.output["artifact_ref"] == "artifact://tenant/activity_output/abc123"

    @pytest.mark.asyncio
    async def test_stream_output_sse_format(self):
        """stream_format='sse' wraps each line in 'data: ...' envelope."""
        ctx = make_ctx(
            "streamOutputNode",
            config={"content": "line1\nline2", "stream_format": "sse"},
        )
        result = await NODE_EXECUTORS["streamOutputNode"].execute(ctx)
        assert result.status == "completed"
        assert result.output["stream_format"] == "sse"
        assert result.output["content"] == "line1\nline2"

    @pytest.mark.asyncio
    async def test_stream_output_json_format(self):
        """stream_format='json' wraps content in a JSON envelope."""
        ctx = make_ctx(
            "streamOutputNode",
            config={"content": "payload", "stream_format": "json"},
        )
        result = await NODE_EXECUTORS["streamOutputNode"].execute(ctx)
        assert result.status == "completed"
        assert result.output["stream_format"] == "json"

    @pytest.mark.asyncio
    async def test_stream_output_collects_upstream_inputs(self):
        """Without explicit content, upstream inputs are concatenated."""
        ctx = make_ctx(
            "streamOutputNode",
            config={"stream_format": "json"},
            inputs={"step-1": {"content": "from upstream"}},
        )
        result = await NODE_EXECUTORS["streamOutputNode"].execute(ctx)
        assert result.status == "completed"
        assert "from upstream" in result.output["content"]

    @pytest.mark.asyncio
    async def test_stream_output_char_count(self):
        """char_count matches the raw content length."""
        content = "hello"
        ctx = make_ctx(
            "streamOutputNode",
            config={"content": content},
        )
        result = await NODE_EXECUTORS["streamOutputNode"].execute(ctx)
        assert result.status == "completed"
        assert result.output["char_count"] == len(content)

    @pytest.mark.asyncio
    async def test_stream_output_no_artifact_without_write_artifact(self):
        """NodeContext without write_artifact sets artifact_ref=None."""
        ctx = make_ctx(
            "streamOutputNode",
            config={"content": "x"},
        )
        result = await NODE_EXECUTORS["streamOutputNode"].execute(ctx)
        assert result.status == "completed"
        assert result.output["artifact_ref"] is None

    @pytest.mark.asyncio
    async def test_stream_output_target_channel_from_config(self):
        """target_channel from config is reflected in output."""
        ctx = make_ctx(
            "streamOutputNode",
            config={"content": "hi", "target_channel": "my-channel"},
        )
        result = await NODE_EXECUTORS["streamOutputNode"].execute(ctx)
        assert result.output["target_channel"] == "my-channel"

    def test_stream_output_classified_beta(self):
        assert NODE_STATUS["streamOutputNode"] is NodeStatus.BETA

    def test_stream_output_runnable_in_production(self):
        assert_node_runnable("streamOutputNode", env="production")
