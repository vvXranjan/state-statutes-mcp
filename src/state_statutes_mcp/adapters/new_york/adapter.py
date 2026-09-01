"""NewYorkAdapter: official NY Senate HTML source.

Source: public NY Senate `https://www.nysenate.gov/legislation/laws/{lawId}/{section}`
First-party, no auth, plain HTTPS. Verified via B81 forensic with fixtures
`tests/fixtures/new_york/*.html` as verbatim slices.

DOM (verified):
- Section identity: <h2 class="nys-openleg-result-title-headline">SECTION 501</h2>
- Law/chapter/article: <h4 class="nys-openleg-result-title-location">State Technology (STT) CHAPTER 57-A, ARTICLE 5</h4>
- Body+catchline+history: <div class="nys-openleg-result-text"> * § 501. Definitions... * NB Repealed July 1, 2028<br /></div>
- Invalid: HTTP 200 but body contains "The requested entry could not be found." and no h2/result-text.

Citation model: TitleRef.identifier = lawId (STT, VAT), ChapterRef.identifier = chapter (57-A, 71), SectionRef.identifier = section (501, 1110). Article remains adapter-internal metadata.

Discovery is intentionally minimal: known lawIds STT/VAT are returned; chapters/sections are from the verified fixture set. This avoids fabricating the full 134-law corpus.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Sequence

from state_statutes_mcp.adapters._fetch import fetch_url
from state_statutes_mcp.adapters._htmltext import strip_tags
from state_statutes_mcp.adapters.base import BaseStateAdapter
from state_statutes_mcp.core.exceptions import (
    NormalizationError,
    RefMismatchError,
    RefNotFoundError,
    UnsupportedRefError,
)
from state_statutes_mcp.models.citation import Citation
from state_statutes_mcp.models.documents import ParsedDocument
from state_statutes_mcp.models.hierarchy import HierarchyLevel, TocNode
from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef
from state_statutes_mcp.models.statute_section import StatuteSection, StatuteStatus

# Minimal known corpus — verified fixtures, not exhaustive NY corpus
_KNOWN_LAWS: dict[str, str] = {
    "STT": "State Technology",
    "VAT": "Vehicle & Traffic",
}
_CHAPTERS: dict[str, list[str]] = {
    "STT": ["57-A"],
    "VAT": ["71"],
}
_SECTIONS: dict[tuple[str, str], list[str]] = {
    ("STT", "57-A"): ["501", "502"],
    ("VAT", "71"): ["1110", "1111"],
}

_NOT_FOUND_MARKER = "The requested entry could not be found."
_H2_RE = re.compile(r'<h2 class="nys-openleg-result-title-headline">\s*SECTION\s+([^<\s]+)\s*</h2>', re.I)
_H4_RE = re.compile(r'<h4 class="nys-openleg-result-title-location">\s*(.*?)\s*</h4>', re.S | re.I)
_RESULT_TEXT_RE = re.compile(r'<div class="nys-openleg-result-text">\s*(.*?)\s*</div>', re.S | re.I)
_LAWID_RE = re.compile(r"\((\w+)\)")
_CHAPTER_RE = re.compile(r"CHAPTER\s+([^\s,]+)", re.I)
_ARTICLE_RE = re.compile(r"ARTICLE\s+([^\s<]+)", re.I)
_NB_RE = re.compile(r"\*\s*NB\s+Repealed.*?(?=<br|</div|$)", re.I | re.S)


def _strip_br_to_nl(html: str) -> str:
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = strip_tags(html)
    # Collapse excessive blank lines but preserve paragraph breaks
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class NewYorkAdapter(BaseStateAdapter):
    """Concrete adapter for New York via public NY Senate HTML."""

    @property
    def state_code(self) -> str:
        return "NY"

    @property
    def state_name(self) -> str:
        return "New York"

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        if isinstance(ref, SectionRef):
            law_id = ref.chapter.title.identifier
            return f"https://www.nysenate.gov/legislation/laws/{law_id}/{ref.identifier}"
        if isinstance(ref, ChapterRef):
            # Chapter page is the law's article list; use lawId + chapter as anchor
            return f"https://www.nysenate.gov/legislation/laws/{ref.title.identifier}/{ref.identifier}"
        if isinstance(ref, TitleRef):
            return f"https://www.nysenate.gov/legislation/laws/{ref.identifier}"
        raise UnsupportedRefError(f"Unsupported ref type for NY: {type(ref).__name__}")

    def list_titles(self) -> Sequence[TocNode]:
        nodes = []
        for law_id, name in sorted(_KNOWN_LAWS.items()):
            nodes.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=law_id,
                    name=f"{name} ({law_id})",
                    ref=TitleRef(state_code="NY", identifier=law_id),
                )
            )
        return tuple(nodes)

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        chapters = _CHAPTERS.get(title_ref.identifier, [])
        return tuple(
            TocNode(
                level=HierarchyLevel.CHAPTER,
                identifier=chap,
                name=f"Chapter {chap}",
                ref=ChapterRef(title=title_ref, identifier=chap),
            )
            for chap in chapters
        )

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        key = (chapter_ref.title.identifier, chapter_ref.identifier)
        sections = _SECTIONS.get(key, [])
        return tuple(
            TocNode(
                level=HierarchyLevel.SECTION,
                identifier=sec,
                name=f"Section {sec}",
                ref=SectionRef(chapter=chapter_ref, identifier=sec),
            )
            for sec in sections
        )

    def _parse_html(self, html: str, ref: SectionRef) -> ParsedDocument:
        if _NOT_FOUND_MARKER in html:
            raise RefNotFoundError(f"NY section {ref.identifier!r} not found (law {ref.chapter.title.identifier}).")

        h2_match = _H2_RE.search(html)
        if h2_match is None:
            raise RefNotFoundError(f"NY section {ref.identifier!r} not found — missing SECTION headline.")

        parsed_section = h2_match.group(1).strip()
        if parsed_section != ref.identifier:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match parsed section {parsed_section!r}."
            )

        h4_match = _H4_RE.search(html)
        law_id_parsed: str | None = None
        chapter_parsed: str | None = None
        if h4_match:
            h4_text = strip_tags(h4_match.group(1))
            m_law = _LAWID_RE.search(h4_text)
            if m_law:
                law_id_parsed = m_law.group(1)
            m_chap = _CHAPTER_RE.search(h4_text)
            if m_chap:
                chapter_parsed = m_chap.group(1)

        if law_id_parsed and law_id_parsed != ref.chapter.title.identifier:
            raise RefMismatchError(
                f"Requested law {ref.chapter.title.identifier!r} does not match parsed law {law_id_parsed!r}."
            )
        if chapter_parsed and chapter_parsed != ref.chapter.identifier:
            # Chapter mismatch is also a mismatch, not silent fallback
            raise RefMismatchError(
                f"Requested chapter {ref.chapter.identifier!r} does not match parsed chapter {chapter_parsed!r}."
            )

        result_match = _RESULT_TEXT_RE.search(html)
        if result_match is None:
            raise NormalizationError("NY page missing result-text.")

        raw_html = result_match.group(1)
        # Preserve NB history separately
        nb_match = _NB_RE.search(raw_html)
        amendment_notes = None
        if nb_match:
            amendment_notes = strip_tags(nb_match.group(0)).strip()

        text = _strip_br_to_nl(raw_html)
        # Heading/catchline is the first line after "§ N."
        heading: str | None = None
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            first = lines[0]
            # First line is like "* § 501. Definitions." or "* § 1110. Obedience..."
            m_heading = re.match(r"^\*\s*§\s*[^.]+\.\s*(.*)", first)
            if m_heading:
                heading = m_heading.group(1).strip() or None
            else:
                heading = first[:200]

        raw_citation = f"{ref.chapter.title.identifier} {ref.identifier}"
        # Use exact lawId + section as raw_citation for normalize identity (must contain ref.identifier)
        # B81 shows raw citation should contain the section identifier; use lawId + section
        return ParsedDocument(
            raw_citation=f"{ref.chapter.title.identifier} {ref.identifier}",
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=self.build_url(ref),
            retrieved_at=datetime.now(timezone.utc),
        )

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        # Exact identity: do not use startswith
        html = fetch_url(self.build_url(ref), what="NY section page")
        parsed = self._parse_html(html, ref)
        return self.normalize(parsed, ref)

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        if ref.state_code != "NY":
            raise NormalizationError(f"NY adapter received wrong state {ref.state_code!r}.")
        # LawId must be in parsed citation (e.g., "STT 501" contains "501" and lawId)
        if ref.identifier not in parsed.raw_citation:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match parsed citation {parsed.raw_citation!r}."
            )
        # Also ensure lawId matches if present in raw_citation
        if ref.chapter.title.identifier not in parsed.raw_citation:
            raise RefMismatchError(
                f"Requested law {ref.chapter.title.identifier!r} does not match parsed citation {parsed.raw_citation!r}."
            )
        status = StatuteStatus.UNKNOWN  # NB Repealed is history, not structured status
        return StatuteSection(
            ref=ref,
            citation=Citation(state_code="NY", raw=parsed.raw_citation),
            heading=parsed.heading,
            text=parsed.text,
            status=status,
            amendment_notes=parsed.amendment_notes,
            source_url=parsed.source_url,
            retrieved_at=parsed.retrieved_at,
        )
