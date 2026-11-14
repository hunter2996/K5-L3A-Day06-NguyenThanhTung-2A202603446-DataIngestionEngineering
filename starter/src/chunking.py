"""Implement fixed-size and structure-aware (paragraph/heading) chunking."""
from __future__ import annotations

import re

from .models import Chunk, DocumentPage

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(•])")
_ORPHAN_HEADING_RE = re.compile(
    r"^(?:"
    r"\d+\.\d+\s+[A-Z]"
    r"|EXAMPLE\s+\d+(?:\.\d+)?"
    r"|TRY IT\s+\d+(?:\.\d+)?"
    r"|Problem|Solution|NOTE|Key Terms|Chapter Review|Formula Review|Chapter Objectives|Introduction|COLLABORATIVE EXERCISE"
    r"|USING THE TI-.*"
    r")$"
)


def fixed_size(page: DocumentPage, size: int = 500, overlap: int = 50) -> list[Chunk]:
    """Split text into fixed-size overlapping character windows and retain page metadata."""
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must satisfy 0 <= overlap < size")

    text = page.text.strip()
    if not text:
        return []

    chunks: list[Chunk] = []
    step = size - overlap
    start = 0
    idx = 0

    while start < len(text):
        end = min(start + size, len(text))
        piece = text[start:end].strip()
        if piece:
            meta = dict(page.metadata)
            meta.update(
                {
                    "chunk_index": idx,
                    "char_len": len(piece),
                    "chunk_strategy": "fixed_size",
                    "char_start": start,
                    "char_end": end,
                }
            )
            chunks.append(
                Chunk(
                    chunk_id=f"{page.document_id}:p{page.page:04d}:fixed:{idx:03d}",
                    document_id=page.document_id,
                    source=page.source,
                    page=page.page,
                    text=piece,
                    metadata=meta,
                )
            )
            idx += 1
        if end >= len(text):
            break
        start += step

    return chunks


def _is_heading_or_label(block: str) -> bool:
    if _ORPHAN_HEADING_RE.match(block):
        return True
    if len(block) <= 85 and block[-1] not in ".?!:”\"" and not any(c in block for c in "=;"):
        if re.match(r"^(?:\d+\.\d+\s+[A-Z]|[A-Z][A-Za-z0-9\s,\-()]+)$", block):
            return True
    return False


def _split_oversized_block(block: str, max_size: int) -> list[str]:
    if len(block) <= max_size:
        return [block]
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(block) if s.strip()]
    if len(sentences) <= 1:
        # Word-boundary fallback for giant tables or lists without sentence breaks.
        words = block.split()
        out: list[str] = []
        buf: list[str] = []
        cur_len = 0
        for w in words:
            add_len = len(w) + (1 if buf else 0)
            if buf and cur_len + add_len > max_size:
                out.append(" ".join(buf))
                buf = [w]
                cur_len = len(w)
            else:
                buf.append(w)
                cur_len += add_len
        if buf:
            out.append(" ".join(buf))
        return out

    pieces: list[str] = []
    cur = ""
    for sent in sentences:
        if len(sent) > max_size:
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.extend(_split_oversized_block(sent, max_size))
        elif not cur:
            cur = sent
        elif len(cur) + 1 + len(sent) <= max_size:
            cur = f"{cur} {sent}"
        else:
            pieces.append(cur)
            cur = sent
    if cur:
        pieces.append(cur)
    return pieces


def by_paragraph(page: DocumentPage, max_size: int = 1000) -> list[Chunk]:
    """Group coherent paragraphs/headings up to max_size, splitting oversized blocks on sentences."""
    if max_size <= 0:
        raise ValueError("max_size must be positive")

    raw_blocks = [b.strip() for b in page.text.split("\n\n") if b.strip()]
    if not raw_blocks:
        return []

    # Step 1: attach standalone headings/labels to the following paragraph so headings stay contextualized.
    attached: list[str] = []
    pending_heading: list[str] = []
    for blk in raw_blocks:
        if _is_heading_or_label(blk):
            pending_heading.append(blk)
        else:
            if pending_heading:
                combined = "\n\n".join([*pending_heading, blk])
                pending_heading.clear()
                attached.append(combined)
            else:
                attached.append(blk)
    if pending_heading:
        if attached:
            attached[-1] = "\n\n".join([attached[-1], *pending_heading])
        else:
            attached.append("\n\n".join(pending_heading))

    # Step 2: split any individual block exceeding max_size along sentence boundaries.
    normalized_blocks: list[str] = []
    for blk in attached:
        normalized_blocks.extend(_split_oversized_block(blk, max_size))

    # Step 3: pack consecutive blocks greedily into chunks <= max_size.
    grouped: list[str] = []
    buf: list[str] = []
    cur_len = 0
    for blk in normalized_blocks:
        sep = 2 if buf else 0
        if buf and cur_len + sep + len(blk) > max_size:
            grouped.append("\n\n".join(buf))
            buf = [blk]
            cur_len = len(blk)
        else:
            buf.append(blk)
            cur_len += sep + len(blk)
    if buf:
        grouped.append("\n\n".join(buf))

    chunks: list[Chunk] = []
    for idx, piece in enumerate(grouped):
        meta = dict(page.metadata)
        meta.update(
            {
                "chunk_index": idx,
                "char_len": len(piece),
                "chunk_strategy": "by_paragraph",
            }
        )
        chunks.append(
            Chunk(
                chunk_id=f"{page.document_id}:p{page.page:04d}:para:{idx:03d}",
                document_id=page.document_id,
                source=page.source,
                page=page.page,
                text=piece,
                metadata=meta,
            )
        )
    return chunks
