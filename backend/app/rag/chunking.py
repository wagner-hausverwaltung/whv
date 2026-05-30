"""Page-aware text chunking for RAG ingestion (ADR-0013 §3).

Splits a document's per-page text into overlapping windows, keeping a
page reference on each chunk so citations can point at a page. Chunk size
is approximated in CHARACTERS (~4 chars/token for German) rather than
real tokens — good enough for an MVP and avoids pulling a tokenizer into
the ingestion path. The retrieval + generation layers cite the page, so
the approximation only affects recall granularity, never correctness.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# ~1000 tokens of German ≈ 4000 chars; ~150 tokens overlap ≈ 600 chars.
_DEFAULT_TARGET_CHARS = 4000
_DEFAULT_OVERLAP_CHARS = 600


@dataclass(frozen=True, slots=True)
class Chunk:
    """A retrievable slice of a document plus the page it started on."""

    text: str
    page: int | None


def chunk_pages(
    pages: Sequence[str],
    *,
    target_chars: int = _DEFAULT_TARGET_CHARS,
    overlap_chars: int = _DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    """Window ``pages`` (0-based list; page number = index + 1) into
    overlapping ``Chunk``s. Blank pages are skipped; each chunk is tagged
    with the 1-based page its start offset falls on.
    """
    if target_chars <= 0:
        raise ValueError("target_chars must be positive")
    if not 0 <= overlap_chars < target_chars:
        raise ValueError("overlap_chars must be in [0, target_chars)")

    # Flatten non-empty pages, recording where each page starts in the
    # combined string so we can attribute a chunk back to a page.
    parts: list[str] = []
    boundaries: list[tuple[int, int]] = []  # (start_offset, page_number)
    offset = 0
    for index, page_text in enumerate(pages):
        cleaned = page_text.strip()
        if not cleaned:
            continue
        if parts:
            parts.append("\n\n")
            offset += 2
        boundaries.append((offset, index + 1))
        parts.append(cleaned)
        offset += len(cleaned)

    full = "".join(parts)
    if not full:
        return []

    def page_at(pos: int) -> int:
        page = boundaries[0][1]
        for start, page_number in boundaries:
            if start <= pos:
                page = page_number
            else:
                break
        return page

    chunks: list[Chunk] = []
    step = target_chars - overlap_chars
    start = 0
    length = len(full)
    while start < length:
        end = min(start + target_chars, length)
        window = full[start:end].strip()
        if window:
            chunks.append(Chunk(text=window, page=page_at(start)))
        if end >= length:
            break
        start += step
    return chunks
