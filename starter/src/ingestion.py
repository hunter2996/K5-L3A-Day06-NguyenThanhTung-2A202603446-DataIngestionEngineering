"""Read and normalize source PDF data with full page traceability."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import pypdf

from .models import DocumentPage

_FOOTER_PATTERNS = [
    re.compile(r"^\s*\d+\s+\d+\s+[•·]\s+.*$"),
    re.compile(r"^\s*\d+(?:\.\d+)?\s+[•·]\s+.*?\s+\d+\s*$"),
    re.compile(r"^\s*\d+\s+[•·]\s+Introduction\s+\d+\s*$"),
    re.compile(r"^\s*Access for free at openstax\.org\s*$", re.IGNORECASE),
    re.compile(r"^\s*\d+\s+[A-Z][A-Z\s]{4,}$"),
]

_BOOK_PAGE_EVEN = re.compile(r"^\s*(\d+)\s+\d+\s+[•·]\s+")
_BOOK_PAGE_ODD = re.compile(r"^\s*\d+(?:\.\d+)?\s+[•·]\s+.*?\s+(\d+)\s*$")

_BLOCK_START_RE = re.compile(
    r"^(?:"
    r"\d+\.\d+\s+[A-Z]"
    r"|EXAMPLE\s+\d+(?:\.\d+)?"
    r"|TRY IT\s+\d+(?:\.\d+)?"
    r"|Figure\s+\d+(?:\.\d+)?"
    r"|Table\s+\d+(?:\.\d+)?"
    r"|NOTE\b"
    r"|COLLABORATIVE EXERCISE\b"
    r"|USING THE TI-"
    r"|Using the TI-"
    r"|Chapter Objectives\b"
    r"|Introduction\b"
    r"|Key Terms\b"
    r"|Chapter Review\b"
    r"|Formula Review\b"
    r"|Problem\b"
    r"|Solution\b"
    r"|[•◦\-]\s+"
    r"|\d+\.\s+"
    r"|[a-z]\.\s+"
    r")"
)

_EXACT_LABEL_RE = re.compile(
    r"^(?:Problem|Solution|NOTE|Key Terms|Chapter Review|Formula Review|Chapter Objectives|Introduction|COLLABORATIVE EXERCISE)$"
)

_LAB_PREFIXES = ("1.5 ", "1.6 ", "2.8 ", "3.6 ")


def extract_book_page(raw_text: str) -> int | None:
    """Parse printed textbook page number from OpenStax running footer when present."""
    for line in raw_text.splitlines()[-4:]:
        m = _BOOK_PAGE_EVEN.match(line)
        if m:
            return int(m.group(1))
        m = _BOOK_PAGE_ODD.match(line)
        if m:
            return int(m.group(1))
    return None


def _is_footer_line(line: str) -> bool:
    return any(pat.match(line) for pat in _FOOTER_PATTERNS)


def _is_short_heading(line: str) -> bool:
    if _EXACT_LABEL_RE.match(line):
        return True
    if len(line) > 72:
        return False
    if line[-1] in ".?!:;,”\"":
        return False
    if re.match(r"^\d+\.\d+\s+[A-Z]", line):
        return True
    # Title-case standalone subheadings like "Levels of Measurement", "Tree Diagrams"
    words = line.split()
    if 1 <= len(words) <= 9 and line[0].isupper() and not any(ch in line for ch in "=+<>"):
        return True
    return False


def normalize_text(text: str) -> str:
    """Normalize Unicode, strip running OpenStax footers, and reconstruct paragraphs."""
    if not text:
        return ""
    cleaned = unicodedata.normalize("NFKC", text)
    cleaned = cleaned.replace("\u200b", "").replace("\ufeff", "").replace("\xa0", " ")

    raw_lines: list[str] = []
    for raw_line in cleaned.splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            raw_lines.append("")
            continue
        if _is_footer_line(line):
            continue
        raw_lines.append(line)

    # Reconstruct paragraphs: preserve structural headings/lists and terminal-line breaks.
    paragraphs: list[str] = []
    current_parts: list[str] = []

    def flush() -> None:
        if current_parts:
            paragraphs.append(" ".join(current_parts).strip())
            current_parts.clear()

    for idx, line in enumerate(raw_lines):
        if not line:
            flush()
            continue

        if current_parts and _BLOCK_START_RE.match(line):
            flush()

        current_parts.append(line)

        next_line = raw_lines[idx + 1] if idx + 1 < len(raw_lines) else ""
        if _is_short_heading(line):
            flush()
        elif line[-1] in ".?!:”\"" and len(line) < 92:
            flush()
        elif next_line and _BLOCK_START_RE.match(next_line):
            flush()

    flush()
    return "\n\n".join(p for p in paragraphs if p)


def _flatten_outline(reader: pypdf.PdfReader, items: list[Any], depth: int = 0) -> list[tuple[int, str, int]]:
    entries: list[tuple[int, str, int]] = []
    for item in items:
        if isinstance(item, list):
            entries.extend(_flatten_outline(reader, item, depth + 1))
        else:
            try:
                page_num = reader.get_destination_page_number(item) + 1
                entries.append((page_num, str(item.title).strip(), depth))
            except Exception:
                continue
    return entries


def build_outline_metadata(reader: pypdf.PdfReader, page_numbers: list[int]) -> dict[int, dict[str, Any]]:
    """Map each physical PDF page to chapter, section, and content_type using PDF outline."""
    entries = _flatten_outline(reader, list(reader.outline or []))
    chapters = [(p, title) for p, title, d in entries if d == 0 and title.startswith("Chapter ")]
    sections = [(p, title) for p, title, d in entries if d >= 1]

    mapping: dict[int, dict[str, Any]] = {}
    for p in page_numbers:
        chapter_title = "Unknown"
        chapter_slug = "unknown"
        for cp, ctitle in chapters:
            if cp <= p:
                chapter_title = ctitle
                m = re.match(r"Chapter\s+(\d+)\s+(.*)", ctitle)
                if m:
                    chapter_slug = f"chapter_{m.group(1)}"
                    chapter_title = f"Chapter {m.group(1)}: {m.group(2)}"

        section_title = chapter_title
        matching_sections = [stitle for sp, stitle in sections if sp == p]
        if matching_sections:
            filtered = [s for s in matching_sections if s not in {"Chapter Objectives", "Introduction"}]
            section_title = " / ".join(filtered) if filtered else matching_sections[-1]
        else:
            for sp, stitle in sections:
                if sp <= p and stitle not in {"Chapter Objectives", "Introduction"}:
                    section_title = stitle

        if section_title in {"Key Terms", "Chapter Review", "Formula Review"} or any(
            part in {"Key Terms", "Chapter Review", "Formula Review"} for part in section_title.split(" / ")
        ):
            content_type = "review"
        elif section_title.startswith(_LAB_PREFIXES):
            content_type = "lab"
        else:
            content_type = "lesson"

        mapping[p] = {
            "chapter": chapter_slug,
            "chapter_title": chapter_title,
            "section": section_title,
            "content_type": content_type,
        }
    return mapping


def load_pdf(
    path: Path,
    document_id: str,
    source: str,
    page_numbers: list[int] | None = None,
    page_metadata_map: dict[int, dict[str, Any]] | None = None,
    error_log: list[dict[str, Any]] | None = None,
) -> list[DocumentPage]:
    """Extract and normalize physical PDF pages while preserving source/page traceability."""
    if not path.exists():
        raise FileNotFoundError(f"Source PDF not found: {path}")

    reader = pypdf.PdfReader(str(path))
    total_pages = len(reader.pages)
    target_pages = page_numbers if page_numbers is not None else list(range(1, total_pages + 1))

    if page_metadata_map is None and reader.outline:
        page_metadata_map = build_outline_metadata(reader, target_pages)

    pages: list[DocumentPage] = []
    for page_num in target_pages:
        if page_num < 1 or page_num > total_pages:
            msg = f"Requested page {page_num} out of bounds (1..{total_pages})"
            if error_log is not None:
                error_log.append({"page": page_num, "issue": "out_of_bounds", "detail": msg})
            continue

        try:
            raw_text = reader.pages[page_num - 1].extract_text() or ""
        except Exception as exc:
            if error_log is not None:
                error_log.append({"page": page_num, "issue": "extract_error", "detail": str(exc)})
            continue

        book_page = extract_book_page(raw_text)
        normalized = normalize_text(raw_text)

        if not normalized:
            if error_log is not None:
                error_log.append({
                    "page": page_num,
                    "issue": "empty_text",
                    "detail": "Page extracted zero characters after normalization (possibly scanned/image page).",
                })
            continue

        if len(normalized) < 350 and error_log is not None:
            error_log.append({
                "page": page_num,
                "issue": "low_text_density",
                "char_count": len(normalized),
                "detail": "Page contains sparse text (figures/tables/calculator screenshots or missing vector math).",
            })

        # Note formula gaps where pypdf omits inline SVG/MathML symbols (e.g., "=  =" or "Where ... = \n")
        if re.search(r"(?:^|\s)=\s*(?:$|[.,;])|\s{3,}", raw_text) and error_log is not None:
            if re.search(r"=\s{2,}=", raw_text):
                error_log.append({
                    "page": page_num,
                    "issue": "omitted_inline_formula_glyphs",
                    "detail": "Blank gaps detected around '=' indicating omitted vector math expressions in PDF.",
                })

        meta = dict((page_metadata_map or {}).get(page_num, {}))
        meta["book_page"] = book_page
        meta["char_count"] = len(normalized)

        pages.append(
            DocumentPage(
                document_id=document_id,
                source=source,
                page=page_num,
                text=normalized,
                metadata=meta,
            )
        )

    return pages
