"""Format-specific document parsers (stdlib only)."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ParsedDocument:
    """Result of parsing a single document."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    format: str = "unknown"


# ---------------------------------------------------------------------------
# Individual parsers
# ---------------------------------------------------------------------------

def parse_text(source: str | Path, *, encoding: str = "utf-8") -> ParsedDocument:
    """Parse a plain-text file or string.

    Args:
        source: File path or raw text content.
        encoding: File encoding (used only when *source* is a path).

    Returns:
        ParsedDocument with the raw text content.
    """
    text, meta = _read_source(source, encoding)
    meta["format"] = "text"
    return ParsedDocument(content=text, metadata=meta, format="text")


def parse_markdown(source: str | Path, *, encoding: str = "utf-8") -> ParsedDocument:
    """Parse a Markdown file or string.

    Strips front-matter (``---`` delimited YAML block) if present and exposes
    it in ``metadata["front_matter"]``.

    Args:
        source: File path or raw Markdown content.
        encoding: File encoding.

    Returns:
        ParsedDocument with Markdown body.
    """
    text, meta = _read_source(source, encoding)
    meta["format"] = "markdown"

    front_matter: str | None = None
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if fm_match:
        front_matter = fm_match.group(1)
        text = text[fm_match.end():]

    if front_matter is not None:
        meta["front_matter"] = front_matter

    return ParsedDocument(content=text.strip(), metadata=meta, format="markdown")


def parse_json(source: str | Path, *, encoding: str = "utf-8") -> ParsedDocument:
    """Parse a JSON file or string into a pretty-printed text representation.

    Args:
        source: File path or raw JSON string.
        encoding: File encoding.

    Returns:
        ParsedDocument whose *content* is the pretty-printed JSON.
    """
    text, meta = _read_source(source, encoding)
    meta["format"] = "json"

    data = json.loads(text)
    pretty = json.dumps(data, indent=2, ensure_ascii=False)
    return ParsedDocument(content=pretty, metadata=meta, format="json")


def parse_csv(source: str | Path, *, encoding: str = "utf-8") -> ParsedDocument:
    """Parse a CSV file or string into a text representation.

    Each row is rendered as ``col1: val1 | col2: val2 | …`` so downstream
    chunking treats it as natural-language-ish text.

    Args:
        source: File path or raw CSV string.
        encoding: File encoding.

    Returns:
        ParsedDocument with row-per-line text content.
    """
    text, meta = _read_source(source, encoding)
    meta["format"] = "csv"

    reader = csv.DictReader(io.StringIO(text))
    lines: list[str] = []
    row_count = 0
    for row in reader:
        parts = [f"{k}: {v}" for k, v in row.items()]
        lines.append(" | ".join(parts))
        row_count += 1

    meta["row_count"] = row_count
    meta["columns"] = reader.fieldnames or []
    return ParsedDocument(content="\n".join(lines), metadata=meta, format="csv")


# ---------------------------------------------------------------------------
# Registry — maps format names to parser functions
# ---------------------------------------------------------------------------

PARSERS: dict[str, Any] = {
    "text": parse_text,
    "txt": parse_text,
    "markdown": parse_markdown,
    "md": parse_markdown,
    "json": parse_json,
    "csv": parse_csv,
}

_EXT_MAP: dict[str, str] = {
    ".txt": "text",
    ".md": "markdown",
    ".markdown": "markdown",
    ".json": "json",
    ".csv": "csv",
}


def detect_format(path: str | Path) -> str:
    """Detect document format from file extension.

    Args:
        path: File path (only the suffix is inspected).

    Returns:
        Canonical format name or ``"text"`` as fallback.
    """
    ext = Path(path).suffix.lower()
    return _EXT_MAP.get(ext, "text")


def parse(source: str | Path, *, fmt: str | None = None, encoding: str = "utf-8") -> ParsedDocument:
    """Auto-detect format and parse *source*.

    Args:
        source: File path or raw content string.
        fmt: Explicit format override (e.g. ``"json"``).  When *None* the
            format is inferred from the file extension if *source* is a path,
            otherwise defaults to ``"text"``.
        encoding: File encoding.

    Returns:
        ParsedDocument produced by the appropriate parser.

    Raises:
        ValueError: If the requested format has no registered parser.
    """
    if fmt is None:
        if isinstance(source, Path) or (isinstance(source, str) and Path(source).suffix):
            fmt = detect_format(source)
        else:
            fmt = "text"

    parser_fn = PARSERS.get(fmt)
    if parser_fn is None:
        raise ValueError(f"Unsupported format: {fmt!r}")
    return parser_fn(source, encoding=encoding)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_source(source: str | Path, encoding: str) -> tuple[str, dict[str, Any]]:
    """Return ``(text, metadata)`` from a path or raw string."""
    path = Path(source) if isinstance(source, str) else source
    if path.is_file():
        text = path.read_text(encoding=encoding)
        meta: dict[str, Any] = {
            "source_path": str(path.resolve()),
            "file_name": path.name,
            "file_size": path.stat().st_size,
        }
        return text, meta
    # Treat source as raw content string
    return str(source), {"source_path": None}
