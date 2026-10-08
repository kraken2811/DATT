"""Document text splitting and semantic chunking with metadata preservation."""

from dataclasses import dataclass, field
import re
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.agent.config import agent_config


@dataclass
class DocumentChunk:
    """Single segmented passage with semantic metadata."""
    content: str
    chunk_index: int
    metadata: dict[str, Any] = field(default_factory=dict)


def extract_section_headers(text: str) -> list[tuple[int, str]]:
    """Locate header positions and titles in markdown / plain text."""
    headers: list[tuple[int, str]] = []
    pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    for m in pattern.finditer(text):
        headers.append((m.start(), m.group(2).strip()))
    return headers


def find_active_header(pos: int, headers: list[tuple[int, str]]) -> str:
    """Find the most recent header prior to character offset pos."""
    active = "General"
    for h_pos, h_title in headers:
        if h_pos <= pos:
            active = h_title
        else:
            break
    return active


def chunk_document(
    text: str,
    doc_metadata: dict[str, Any] | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[DocumentChunk]:
    """Split raw document text into overlapping chunks with section metadata.

    Args:
        text: Raw document string.
        doc_metadata: Global metadata of the source document (title, source, type).
        chunk_size: Maximum characters per chunk (default from config).
        chunk_overlap: Overlap between consecutive chunks.

    Returns:
        List of DocumentChunk instances.
    """
    size = chunk_size or agent_config.rag_chunk_size
    overlap = chunk_overlap or agent_config.rag_chunk_overlap
    base_meta = dict(doc_metadata or {})

    # Detect headers to enrich chunk metadata
    headers = extract_section_headers(text)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=["\n## ", "\n### ", "\n#### ", "\n\n", "\n", ". ", " ", ""],
        length_function=len,
    )

    raw_chunks = splitter.split_text(text)
    chunks: list[DocumentChunk] = []

    # Map chunks back to text to infer active section
    search_start = 0
    for idx, chunk_text in enumerate(raw_chunks):
        cleaned = chunk_text.strip()
        if not cleaned:
            continue

        found_pos = text.find(cleaned[:50], search_start) if len(cleaned) >= 50 else text.find(cleaned, search_start)
        pos = found_pos if found_pos != -1 else search_start
        search_start = max(search_start, pos)

        section = find_active_header(pos, headers)

        chunk_meta = {
            **base_meta,
            "chunk_index": idx,
            "section": section,
            "char_count": len(cleaned),
        }
        # If the input text has page markers like "--- Page X ---"
        page_match = re.search(r"<!--\s*page\s*(\d+)\s*-->|\[Page\s*(\d+)\]", cleaned, re.IGNORECASE)
        if page_match:
            chunk_meta["page"] = int(page_match.group(1) or page_match.group(2))

        chunks.append(DocumentChunk(content=cleaned, chunk_index=idx, metadata=chunk_meta))

    return chunks
