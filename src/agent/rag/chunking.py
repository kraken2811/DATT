"""Document text splitting and semantic chunking with metadata preservation."""

from dataclasses import dataclass, field
import re
import unicodedata
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.agent.config import agent_config


RAG_PIPELINE_VERSION = "2"


@dataclass
class DocumentChunk:
    """Single segmented passage with semantic metadata."""
    content: str
    chunk_index: int
    metadata: dict[str, Any] = field(default_factory=dict)


def _normalize_label(value: str) -> str:
    """Normalize headings for robust Vietnamese/English structural checks."""
    raw = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


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


def is_low_value_chunk(section: str, content: str) -> bool:
    """Reject table-of-contents/navigation chunks that pollute semantic retrieval."""
    normalized_section = _normalize_label(section)
    low_value_sections = {
        "muc luc",
        "table of contents",
        "contents",
        "navigation",
        "index",
    }
    if normalized_section in low_value_sections:
        return True

    lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
    if len(lines) < 3:
        return False

    markdown_link_lines = sum(
        1
        for line in lines
        if re.search(r"\[[^\]]+\]\([^\)]+\)", line)
        or re.match(r"^\s*\d+[.)]\s+\[[^\]]+\]", line)
    )
    anchor_lines = sum(1 for line in lines if "(#" in line and "]" in line)
    navigation_ratio = max(markdown_link_lines, anchor_lines) / max(len(lines), 1)
    return navigation_ratio >= 0.60


def embedding_text_for_chunk(chunk: DocumentChunk, document_title: str | None = None) -> str:
    """Build embedding input with document and section context while preserving raw passage separately."""
    title = (document_title or chunk.metadata.get("title") or "").strip()
    section = str(chunk.metadata.get("section") or "General").strip()
    parts: list[str] = []
    if title:
        parts.append(f"Document: {title}")
    if section and section != "General":
        parts.append(f"Section: {section}")
    parts.append(chunk.content)
    return "\n".join(parts)


def chunk_document(
    text: str,
    doc_metadata: dict[str, Any] | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[DocumentChunk]:
    """Split raw document text into overlapping chunks with section metadata.

    Navigation-only chunks such as a Markdown table of contents are intentionally
    excluded from the knowledge base because they tend to rank highly while
    containing little answerable content.
    """
    size = chunk_size or agent_config.rag_chunk_size
    overlap = chunk_overlap or agent_config.rag_chunk_overlap
    base_meta = dict(doc_metadata or {})

    headers = extract_section_headers(text)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=["\n## ", "\n### ", "\n#### ", "\n\n", "\n", ". ", " ", ""],
        length_function=len,
    )

    raw_chunks = splitter.split_text(text)
    chunks: list[DocumentChunk] = []

    search_start = 0
    output_index = 0
    for chunk_text in raw_chunks:
        cleaned = chunk_text.strip()
        if not cleaned:
            continue

        found_pos = text.find(cleaned[:50], search_start) if len(cleaned) >= 50 else text.find(cleaned, search_start)
        pos = found_pos if found_pos != -1 else search_start
        search_start = max(search_start, pos)
        section = find_active_header(pos, headers)

        if is_low_value_chunk(section, cleaned):
            continue

        chunk_meta = {
            **base_meta,
            "chunk_index": output_index,
            "section": section,
            "char_count": len(cleaned),
            "rag_pipeline_version": RAG_PIPELINE_VERSION,
        }

        page_match = re.search(r"<!--\s*page\s*(\d+)\s*-->|\[Page\s*(\d+)\]", cleaned, re.IGNORECASE)
        if page_match:
            chunk_meta["page"] = int(page_match.group(1) or page_match.group(2))

        chunks.append(DocumentChunk(content=cleaned, chunk_index=output_index, metadata=chunk_meta))
        output_index += 1

    return chunks
