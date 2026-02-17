"""Comprehensive tests for the DocForge pipeline — parsers, chunker, and pipeline.

Covers: text/markdown/JSON/CSV parsing, chunking (size, overlap, edge cases),
pipeline ingest, embed stub, and search stub.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from integrations.docforge.chunker import Chunk, chunk_text
from integrations.docforge.parsers import (
    ParsedDocument,
    detect_format,
    parse,
    parse_csv,
    parse_json,
    parse_markdown,
    parse_text,
)
from integrations.docforge.pipeline import DocForgePipeline


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def pipeline() -> DocForgePipeline:
    """Default pipeline with small chunk settings for testing."""
    return DocForgePipeline(chunk_size=64, overlap=8)


@pytest.fixture()
def txt_file(tmp_path: Path) -> Path:
    """Temporary plain-text file."""
    p = tmp_path / "sample.txt"
    p.write_text("Hello world. This is a test document.", encoding="utf-8")
    return p


@pytest.fixture()
def md_file(tmp_path: Path) -> Path:
    """Temporary Markdown file with front-matter."""
    content = (
        "---\ntitle: Test\nauthor: Bot\n---\n\n"
        "# Heading\n\nSome **bold** text and a paragraph."
    )
    p = tmp_path / "readme.md"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture()
def md_file_no_front_matter(tmp_path: Path) -> Path:
    """Markdown file without front-matter."""
    p = tmp_path / "plain.md"
    p.write_text("# Just a heading\n\nParagraph here.", encoding="utf-8")
    return p


@pytest.fixture()
def json_file(tmp_path: Path) -> Path:
    """Temporary JSON file."""
    data = {"name": "Archon", "version": 1, "features": ["rag", "agents"]}
    p = tmp_path / "data.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture()
def csv_file(tmp_path: Path) -> Path:
    """Temporary CSV file."""
    p = tmp_path / "data.csv"
    p.write_text("id,name,score\n1,Alice,95\n2,Bob,87\n3,Carol,91\n", encoding="utf-8")
    return p


@pytest.fixture()
def long_text() -> str:
    """Text longer than default chunk_size to exercise multi-chunk splitting."""
    return " ".join(f"word{i}" for i in range(200))


# ═══════════════════════════════════════════════════════════════════════
# Parsers
# ═══════════════════════════════════════════════════════════════════════


class TestParseText:
    """Tests for plain-text parsing."""

    def test_parse_text_from_file(self, txt_file: Path) -> None:
        doc = parse_text(txt_file)
        assert doc.format == "text"
        assert "Hello world" in doc.content
        assert doc.metadata["file_name"] == "sample.txt"
        assert doc.metadata["source_path"] is not None

    def test_parse_text_from_string(self) -> None:
        doc = parse_text("Raw string input")
        assert doc.format == "text"
        assert doc.content == "Raw string input"
        assert doc.metadata["source_path"] is None

    def test_parse_text_empty_string(self) -> None:
        doc = parse_text("")
        assert doc.content == ""
        assert doc.format == "text"

    def test_parse_text_unicode(self) -> None:
        doc = parse_text("日本語テスト 🎉")
        assert "日本語" in doc.content


class TestParseMarkdown:
    """Tests for Markdown parsing."""

    def test_parse_markdown_with_front_matter(self, md_file: Path) -> None:
        doc = parse_markdown(md_file)
        assert doc.format == "markdown"
        assert "front_matter" in doc.metadata
        assert "title: Test" in doc.metadata["front_matter"]
        assert "# Heading" in doc.content
        # Front-matter block itself should NOT appear in content
        assert "---" not in doc.content

    def test_parse_markdown_no_front_matter(self, md_file_no_front_matter: Path) -> None:
        doc = parse_markdown(md_file_no_front_matter)
        assert doc.format == "markdown"
        assert "front_matter" not in doc.metadata
        assert "# Just a heading" in doc.content

    def test_parse_markdown_from_string(self) -> None:
        doc = parse_markdown("# Title\n\nBody text here.")
        assert doc.format == "markdown"
        assert "Body text here." in doc.content

    def test_parse_markdown_empty(self) -> None:
        doc = parse_markdown("")
        assert doc.content == ""


class TestParseJSON:
    """Tests for JSON parsing."""

    def test_parse_json_from_file(self, json_file: Path) -> None:
        doc = parse_json(json_file)
        assert doc.format == "json"
        parsed = json.loads(doc.content)
        assert parsed["name"] == "Archon"
        assert parsed["version"] == 1

    def test_parse_json_from_string(self) -> None:
        doc = parse_json('{"key": "value"}')
        assert doc.format == "json"
        assert '"key": "value"' in doc.content

    def test_parse_json_pretty_printed(self) -> None:
        doc = parse_json('{"a":1}')
        assert "\n" in doc.content  # pretty-printed has newlines

    def test_parse_json_invalid_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            parse_json("not valid json {{{")

    def test_parse_json_array(self) -> None:
        doc = parse_json('[1, 2, 3]')
        parsed = json.loads(doc.content)
        assert parsed == [1, 2, 3]


class TestParseCSV:
    """Tests for CSV parsing."""

    def test_parse_csv_from_file(self, csv_file: Path) -> None:
        doc = parse_csv(csv_file)
        assert doc.format == "csv"
        assert doc.metadata["row_count"] == 3
        assert doc.metadata["columns"] == ["id", "name", "score"]
        assert "Alice" in doc.content

    def test_parse_csv_from_string(self) -> None:
        doc = parse_csv("col_a,col_b\nx,y\n")
        assert doc.format == "csv"
        assert doc.metadata["row_count"] == 1
        assert "col_a: x" in doc.content

    def test_parse_csv_row_format(self) -> None:
        doc = parse_csv("h1,h2\nv1,v2\n")
        assert "h1: v1 | h2: v2" in doc.content

    def test_parse_csv_empty_body(self) -> None:
        doc = parse_csv("a,b\n")
        assert doc.metadata["row_count"] == 0
        assert doc.content == ""


# ── Auto-detection & parse() dispatcher ───────────────────────────────


class TestDetectFormat:
    """Tests for format auto-detection."""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("doc.txt", "text"),
            ("readme.md", "markdown"),
            ("readme.markdown", "markdown"),
            ("data.json", "json"),
            ("sheet.csv", "csv"),
            ("unknown.xyz", "text"),  # fallback
        ],
    )
    def test_detect_format(self, path: str, expected: str) -> None:
        assert detect_format(path) == expected


class TestParseDispatcher:
    """Tests for the top-level parse() function."""

    def test_parse_auto_detect_txt(self, txt_file: Path) -> None:
        doc = parse(txt_file)
        assert doc.format == "text"

    def test_parse_auto_detect_md(self, md_file: Path) -> None:
        doc = parse(md_file)
        assert doc.format == "markdown"

    def test_parse_auto_detect_json(self, json_file: Path) -> None:
        doc = parse(json_file)
        assert doc.format == "json"

    def test_parse_auto_detect_csv(self, csv_file: Path) -> None:
        doc = parse(csv_file)
        assert doc.format == "csv"

    def test_parse_explicit_fmt_override(self, txt_file: Path) -> None:
        doc = parse(txt_file, fmt="text")
        assert doc.format == "text"

    def test_parse_unsupported_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported format"):
            parse("anything", fmt="xml")

    def test_parse_raw_string_defaults_to_text(self) -> None:
        doc = parse("just a string")
        assert doc.format == "text"


# ═══════════════════════════════════════════════════════════════════════
# Chunker
# ═══════════════════════════════════════════════════════════════════════


class TestChunkText:
    """Tests for chunk_text() — sizes, overlap, edge cases."""

    def test_single_chunk_short_text(self) -> None:
        chunks = chunk_text("Short.", chunk_size=512, overlap=64)
        assert len(chunks) == 1
        assert chunks[0].text == "Short."
        assert chunks[0].index == 0

    def test_multiple_chunks(self, long_text: str) -> None:
        chunks = chunk_text(long_text, chunk_size=100, overlap=10)
        assert len(chunks) > 1
        # Indices are sequential
        for i, c in enumerate(chunks):
            assert c.index == i

    def test_chunk_respects_max_size(self, long_text: str) -> None:
        size = 80
        chunks = chunk_text(long_text, chunk_size=size, overlap=10)
        for c in chunks:
            assert c.char_count <= size

    def test_overlap_shared_text(self) -> None:
        text = "a" * 200
        chunks = chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks) >= 2
        # The end of chunk N should overlap with the start of chunk N+1
        for i in range(len(chunks) - 1):
            end_of_current = chunks[i].metadata["end_char"]
            start_of_next = chunks[i + 1].metadata["start_char"]
            assert start_of_next < end_of_current  # overlap exists

    def test_zero_overlap(self) -> None:
        text = "abcdefghij" * 10  # 100 chars
        chunks = chunk_text(text, chunk_size=25, overlap=0)
        assert len(chunks) >= 4
        for c in chunks:
            assert c.char_count <= 25

    def test_empty_text(self) -> None:
        assert chunk_text("", chunk_size=100, overlap=10) == []

    def test_metadata_propagated(self) -> None:
        meta = {"source": "test"}
        chunks = chunk_text("Hello world", chunk_size=512, overlap=0, metadata=meta)
        assert chunks[0].metadata["source"] == "test"
        assert "chunk_index" in chunks[0].metadata

    def test_invalid_chunk_size_raises(self) -> None:
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            chunk_text("text", chunk_size=0, overlap=0)

    def test_negative_overlap_raises(self) -> None:
        with pytest.raises(ValueError, match="overlap must be non-negative"):
            chunk_text("text", chunk_size=10, overlap=-1)

    def test_overlap_gte_chunk_size_raises(self) -> None:
        with pytest.raises(ValueError, match="overlap must be less than chunk_size"):
            chunk_text("text", chunk_size=10, overlap=10)

    def test_chunk_char_count_property(self) -> None:
        c = Chunk(text="hello", index=0)
        assert c.char_count == 5

    def test_single_char_text(self) -> None:
        chunks = chunk_text("X", chunk_size=10, overlap=0)
        assert len(chunks) == 1
        assert chunks[0].text == "X"

    def test_text_exactly_chunk_size(self) -> None:
        text = "a" * 50
        chunks = chunk_text(text, chunk_size=50, overlap=0)
        assert len(chunks) == 1

    def test_chunk_size_one(self) -> None:
        chunks = chunk_text("abc", chunk_size=1, overlap=0)
        assert len(chunks) >= 1
        # All chunks produced, forward progress guaranteed


# ═══════════════════════════════════════════════════════════════════════
# Pipeline
# ═══════════════════════════════════════════════════════════════════════


class TestDocForgePipelineInit:
    """Pipeline construction."""

    def test_default_settings(self) -> None:
        p = DocForgePipeline()
        assert p.chunk_size == 512
        assert p.overlap == 64
        assert p._store == {}

    def test_custom_settings(self) -> None:
        p = DocForgePipeline(chunk_size=256, overlap=32)
        assert p.chunk_size == 256
        assert p.overlap == 32


class TestPipelineParse:
    """Pipeline.parse() delegates correctly."""

    def test_parse_txt_file(self, pipeline: DocForgePipeline, txt_file: Path) -> None:
        doc = pipeline.parse(txt_file)
        assert isinstance(doc, ParsedDocument)
        assert doc.format == "text"

    def test_parse_md_file(self, pipeline: DocForgePipeline, md_file: Path) -> None:
        doc = pipeline.parse(md_file)
        assert doc.format == "markdown"

    def test_parse_json_file(self, pipeline: DocForgePipeline, json_file: Path) -> None:
        doc = pipeline.parse(json_file)
        assert doc.format == "json"

    def test_parse_csv_file(self, pipeline: DocForgePipeline, csv_file: Path) -> None:
        doc = pipeline.parse(csv_file)
        assert doc.format == "csv"

    def test_parse_raw_string(self, pipeline: DocForgePipeline) -> None:
        doc = pipeline.parse("raw content", fmt="text")
        assert doc.content == "raw content"


class TestPipelineChunk:
    """Pipeline.chunk() produces correct chunks."""

    def test_chunk_document(self, pipeline: DocForgePipeline) -> None:
        doc = ParsedDocument(content="word " * 100, metadata={"src": "test"}, format="text")
        chunks = pipeline.chunk(doc)
        assert len(chunks) >= 1
        assert all(isinstance(c, Chunk) for c in chunks)
        # Metadata from doc should be propagated
        assert chunks[0].metadata.get("src") == "test"


class TestPipelineEmbed:
    """Pipeline.embed() stub returns zero vectors."""

    def test_embed_returns_vectors(self, pipeline: DocForgePipeline) -> None:
        chunks = [Chunk(text="hello", index=0), Chunk(text="world", index=1)]
        vectors = pipeline.embed(chunks)
        assert len(vectors) == 2
        assert all(len(v) == 384 for v in vectors)
        assert all(val == 0.0 for v in vectors for val in v)

    def test_embed_empty_list(self, pipeline: DocForgePipeline) -> None:
        assert pipeline.embed([]) == []


class TestPipelineSearch:
    """Pipeline.search() stub returns stored chunks."""

    def test_search_empty_store(self, pipeline: DocForgePipeline) -> None:
        results = pipeline.search("anything")
        assert results == []

    def test_search_returns_top_k(self, pipeline: DocForgePipeline, txt_file: Path) -> None:
        pipeline.ingest(txt_file)
        results = pipeline.search("hello", top_k=2)
        assert len(results) <= 2
        assert all(isinstance(c, Chunk) for c in results)

    def test_search_respects_top_k_limit(
        self, pipeline: DocForgePipeline, tmp_path: Path
    ) -> None:
        # Ingest enough text to produce multiple chunks
        big_file = tmp_path / "big.txt"
        big_file.write_text("word " * 500, encoding="utf-8")
        pipeline.ingest(big_file)
        all_results = pipeline.search("query", top_k=100)
        limited = pipeline.search("query", top_k=2)
        assert len(limited) <= 2
        assert len(limited) <= len(all_results)


class TestPipelineIngest:
    """End-to-end ingest: parse → chunk → embed → store."""

    def test_ingest_txt_file(self, pipeline: DocForgePipeline, txt_file: Path) -> None:
        chunks = pipeline.ingest(txt_file)
        assert len(chunks) >= 1
        assert all(isinstance(c, Chunk) for c in chunks)

    def test_ingest_md_file(self, pipeline: DocForgePipeline, md_file: Path) -> None:
        chunks = pipeline.ingest(md_file)
        assert len(chunks) >= 1

    def test_ingest_json_file(self, pipeline: DocForgePipeline, json_file: Path) -> None:
        chunks = pipeline.ingest(json_file)
        assert len(chunks) >= 1

    def test_ingest_csv_file(self, pipeline: DocForgePipeline, csv_file: Path) -> None:
        chunks = pipeline.ingest(csv_file)
        assert len(chunks) >= 1

    def test_ingest_raw_string(self, pipeline: DocForgePipeline) -> None:
        chunks = pipeline.ingest("Some raw text content", fmt="text")
        assert len(chunks) >= 1

    def test_ingest_stores_chunks(self, pipeline: DocForgePipeline, txt_file: Path) -> None:
        pipeline.ingest(txt_file)
        assert len(pipeline._store) == 1

    def test_ingest_multiple_documents(
        self, pipeline: DocForgePipeline, txt_file: Path, md_file: Path
    ) -> None:
        pipeline.ingest(txt_file)
        pipeline.ingest(md_file)
        assert len(pipeline._store) == 2

    def test_ingest_same_content_deduplicates(self, pipeline: DocForgePipeline) -> None:
        pipeline.ingest("identical content", fmt="text")
        pipeline.ingest("identical content", fmt="text")
        # Same content → same doc_id → overwritten in store
        assert len(pipeline._store) == 1

    def test_ingest_searchable_after(self, pipeline: DocForgePipeline, txt_file: Path) -> None:
        pipeline.ingest(txt_file)
        results = pipeline.search("hello")
        assert len(results) >= 1

    def test_doc_id_deterministic(self) -> None:
        doc = ParsedDocument(content="stable content", format="text")
        id1 = DocForgePipeline._doc_id(doc)
        id2 = DocForgePipeline._doc_id(doc)
        assert id1 == id2
        assert len(id1) == 16

    def test_doc_id_differs_for_different_content(self) -> None:
        d1 = ParsedDocument(content="aaa", format="text")
        d2 = ParsedDocument(content="bbb", format="text")
        assert DocForgePipeline._doc_id(d1) != DocForgePipeline._doc_id(d2)
