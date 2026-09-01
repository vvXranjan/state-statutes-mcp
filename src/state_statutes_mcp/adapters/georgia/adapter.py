"""GeorgiaAdapter: Official Code of Georgia Annotated (OCGA) — Archive.org bulk.

Source: ``gov.ga.ocga.2024`` collection on archive.org
``https://archive.org/details/gov.ga.ocga.2024``
Publishers: The Code Revision Commission, Office of Legislative Counsel,
LexisNexis, under authority of the State of Georgia, Secretary of State
certification (certified statutory portion as enacted by General Assembly).
Item Size 33.0G, data received via Open Records Act request, public domain
per U.S. Supreme Court order (Georgia v. Public.Resource.Org, 18-1150).
Data current as of August 2024. Addeddate 2024-12-10.

Provenance for this adapter's fixtures:
- Primary: ``T49-T50 Ch1-12 (V38) 2023_djvu.txt`` (2,616,399 bytes,
  SHA-256 ``0dabb86389449bbf818c2618ead71432fa14befe1e69a424eb3f275ecb79942d``,
  ``https://archive.org/download/gov.ga.ocga.2024/T49-T50%20Ch1-12%20%28V38%29%202023_djvu.txt``)
  Covers Title 49 Social Services and Title 50 State Government Ch 1-12
  (includes Title 50 Chapter 3, Sections 50-3-1 through 50-3-30+).
- Secondary PDF: ``T49-T50 Ch1-12 (V38) 2023.pdf`` (3,503,012 bytes,
  SHA-256 ``b1a50b0e39170cee248c1f06a2b3a241dfe096766c219dc7477cdde582c047b7``,
  PDF 1.4, 1010 pages, same URL with .pdf).

Fixtures are verbatim slices of the djvu.txt (not re-typed), 1,258,968 bytes
for ``ga_T50_slice.txt`` (SHA ``03fe4f89db6e42e6b32cdcef9b27ed51c8339ffe2991352c4234faf9f821397c``)
and 82,326 bytes for ``ga_T50_100_slice.txt`` (SHA ``d8ea07e88671b74ce6078f94575fd1ce4d75d314b806308067db273927a5c822``)
extracted between line 765 (49-1-1) and line 40128 (50-3-30) for the main slice
and 50-3-100..105 for the 100 slice, with a provenance header prepended.
Tests use the slices; no secondary/legal-aggregator site (Justia/Lexis)
is treated as authoritative.

Citation form is ``{title}-{chapter}-{section}`` with optional dotted
and letter suffixes (e.g. ``50-3-1``, ``50-3-4.1``, ``50-3-10``, ``50-3-100``).
Title and chapter are the leading ``title`` and ``chapter`` segments of the
full citation. This adapter exposes the full hyphenated citation as the
``SectionRef.identifier`` (mirroring NJ's full-citation key), and derives
title/chapter from it. Lookup is exact — no prefix or ``startswith``.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Sequence

from state_statutes_mcp.adapters.base import BaseStateAdapter
from state_statutes_mcp.core.exceptions import (
    AdapterUnavailableError,
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

# Exact header: citation at column 0, dot, then heading text.
# Matches "50-3-1. Description ..." and "50-3-4.1. Schools, ..." but not
# page header "50-3-1 STATE FLAG..." (no dot after citation) nor TOC entry
# "50-3-1." alone (heading group would be empty, so we require heading).
_HEADER_RE = re.compile(rb"^(\d+)-(\d+)-(\S+)\.\s+(.+)")
# Title/chapter sort: numeric prefix
_SORT_RE = re.compile(r"^(\d+)(.*)$")


class _SectionRec(NamedTuple):
    title_id: str
    chapter_id: str
    section_id: str
    citation: str
    heading: str
    text: str


def _sort_key(identifier: str) -> tuple[int, str]:
    m = _SORT_RE.match(identifier)
    if m:
        return (int(m.group(1)), m.group(2) or "")
    return (10**9, identifier)


class GeorgiaAdapter(BaseStateAdapter):
    """Concrete adapter for Georgia OCGA (Archive.org bulk, BULK_TEXT)."""

    def __init__(self, data_path: str | Path | None = None) -> None:
        self._data_path = Path(data_path) if data_path is not None else None
        self._index: dict[str, _SectionRec] | None = None
        self._titles: tuple[TocNode, ...] | None = None
        self._chapters_map: dict[str, tuple[str, ...]] | None = None
        self._sections_map: dict[tuple[str, str], tuple[str, ...]] | None = None

    @property
    def state_code(self) -> str:
        return "GA"

    @property
    def state_name(self) -> str:
        return "Georgia"

    def _resolve_data_path(self) -> Path:
        if self._data_path is not None:
            if self._data_path.is_file():
                return self._data_path
            # Also allow directory containing slices
            if self._data_path.is_dir():
                # Prefer combined bulk if exists, else first slice
                for cand in ["ga_T50_slice.txt", "georgia_bulk.txt"]:
                    p = self._data_path / cand
                    if p.is_file():
                        return p
                raise AdapterUnavailableError(
                    f"Georgia bulk file not found in directory {str(self._data_path)!r}."
                )
            raise AdapterUnavailableError(
                f"Georgia OCGA file not found at {str(self._data_path)!r}."
            )
        env = os.environ.get("GEORGIA_OCGA_TXT", "").strip()
        if env:
            p = Path(env)
            if p.is_file():
                return p
            if p.is_dir():
                for cand in ["ga_T50_slice.txt", "georgia_bulk.txt"]:
                    q = p / cand
                    if q.is_file():
                        return q
                raise AdapterUnavailableError(
                    f"GEORGIA_OCGA_TXT directory contains no known bulk file: {env!r}."
                )
            raise AdapterUnavailableError(
                f"GEORGIA_OCGA_TXT is set but is not a file: {env!r}."
            )
        # Default: try repository fixtures (supports tests without env)
        # Walk from this file to repo root: .../adapters/georgia/adapter.py -> .../tests/fixtures/georgia
        default = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "georgia" / "ga_T50_slice.txt"
        if default.is_file():
            return default
        raise AdapterUnavailableError(
            "Georgia OCGA bulk file not configured. Set GEORGIA_OCGA_TXT to the "
            "official djvu.txt slice or pass data_path."
        )

    def _ensure_index(self) -> None:
        if self._index is not None:
            return
        self._index = self._build_index()
        self._titles = self._build_titles()
        self._chapters_map = self._build_chapters_map()
        self._sections_map = self._build_sections_map()

    def _build_index(self) -> dict[str, _SectionRec]:
        path = self._resolve_data_path()
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise AdapterUnavailableError(
                f"Could not read Georgia bulk at {str(path)!r}: {exc}"
            ) from exc
        # Also try to append the 100 slice if primary is the main slice and secondary exists nearby
        secondary = path.parent / "ga_T50_100_slice.txt"
        if secondary.is_file() and path.name == "ga_T50_slice.txt":
            try:
                raw2 = secondary.read_bytes()
                # Avoid double-counting provenance header: just concat bodies
                raw = raw + b"\n" + raw2
            except OSError:
                pass
        raw_lines = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")
        index: dict[str, _SectionRec] = {}
        i = 0
        n = len(raw_lines)
        while i < n:
            line = raw_lines[i]
            m = _HEADER_RE.match(line)
            if m is None:
                i += 1
                continue
            # token is leading citation before dot
            try:
                token = line.split()[0].decode("utf-8", errors="replace").rstrip(".")
            except Exception:
                i += 1
                continue
            # Must split into title-chapter-section (section may contain dot)
            try:
                title_id, chapter_id, section_id = token.split("-", 2)
            except ValueError:
                i += 1
                continue
            # Validate numeric title/chapter
            if not title_id.isdigit() or not chapter_id.isdigit():
                i += 1
                continue
            # heading via regex group 4 (avoids dot-in-citation confusion for 50-3-4.1)
            try:
                caption = m.group(4).decode("utf-8", errors="replace").strip()
            except Exception:
                heading_full = line.decode("utf-8", errors="replace").strip()
                dot = heading_full.find(".")
                caption = heading_full[dot + 1 :].strip() if dot != -1 else heading_full
            if not caption:
                i += 1
                continue
            # Body: until next header with heading
            body_parts: list[str] = []
            j = i + 1
            while j < n:
                nxt = raw_lines[j]
                if _HEADER_RE.match(nxt) is not None:
                    # Next real section starts
                    break
                # Decode, preserve even empty lines as paragraph breaks
                body_parts.append(nxt.decode("utf-8", errors="replace"))
                j += 1
            text = "\n".join(body_parts).strip()
            # Skip sections with no body text
            if not text:
                text = caption
            rec = _SectionRec(
                title_id=title_id,
                chapter_id=chapter_id,
                section_id=section_id,
                citation=token,
                heading=caption,
                text=text,
            )
            # Exact map: first wins, no overwrite (preserves first real occurrence)
            if token not in index:
                index[token] = rec
            i = j
        if not index:
            raise AdapterUnavailableError(
                f"Georgia bulk at {str(path)!r} produced no sections; check format."
            )
        return index

    def _build_titles(self) -> tuple[TocNode, ...]:
        assert self._index is not None
        seen: set[str] = set()
        nodes: list[TocNode] = []
        for rec in self._index.values():
            if rec.title_id in seen:
                continue
            seen.add(rec.title_id)
            nodes.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=rec.title_id,
                    name=f"Title {rec.title_id}",
                    ref=TitleRef(state_code="GA", identifier=rec.title_id),
                )
            )
        nodes.sort(key=lambda n: _sort_key(n.identifier))
        return tuple(nodes)

    def _build_chapters_map(self) -> dict[str, tuple[str, ...]]:
        assert self._index is not None
        mapping: dict[str, set[str]] = {}
        for rec in self._index.values():
            mapping.setdefault(rec.title_id, set()).add(rec.chapter_id)
        return {
            title: tuple(sorted(chaps, key=_sort_key))
            for title, chaps in mapping.items()
        }

    def _build_sections_map(self) -> dict[tuple[str, str], tuple[str, ...]]:
        assert self._index is not None
        mapping: dict[tuple[str, str], list[str]] = {}
        for rec in self._index.values():
            mapping.setdefault((rec.title_id, rec.chapter_id), []).append(rec.citation)

        def _section_sort(citation: str) -> tuple[int, str]:
            try:
                _, _, sec = citation.split("-", 2)
            except ValueError:
                return (10**9, citation)
            return _sort_key(sec)

        return {
            key: tuple(sorted(set(cites), key=_section_sort))
            for key, cites in mapping.items()
        }

    def list_titles(self) -> Sequence[TocNode]:
        self._ensure_index()
        assert self._titles is not None
        return self._titles

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        self._ensure_index()
        assert self._chapters_map is not None
        chapter_ids = self._chapters_map.get(title_ref.identifier, ())
        return tuple(
            TocNode(
                level=HierarchyLevel.CHAPTER,
                identifier=chap,
                name=f"Chapter {chap}",
                ref=ChapterRef(title=title_ref, identifier=chap),
            )
            for chap in chapter_ids
        )

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        self._ensure_index()
        assert self._sections_map is not None
        title_id = chapter_ref.title.identifier
        chapter_id = chapter_ref.identifier
        citations = self._sections_map.get((title_id, chapter_id), ())
        return tuple(
            TocNode(
                level=HierarchyLevel.SECTION,
                identifier=cite,
                name=f"Section {cite}",
                ref=SectionRef(chapter=chapter_ref, identifier=cite),
            )
            for cite in citations
        )

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        self._ensure_index()
        assert self._index is not None
        citation_key = ref.identifier.strip()
        # Exact identity: no startswith, no prefix
        rec = self._index.get(citation_key)
        if rec is None:
            raise RefNotFoundError(
                f"Georgia section {citation_key!r} not found in OCGA bulk."
            )
        # Derive expected title/chapter from citation to catch cross-title mismatches
        try:
            exp_title, exp_chapter, _ = citation_key.split("-", 2)
        except ValueError:
            raise RefNotFoundError(f"Malformed Georgia citation {citation_key!r}.")
        # Verify ref's title/chapter matches citation's title/chapter (exact)
        if ref.chapter.title.identifier != exp_title or ref.chapter.identifier != exp_chapter:
            raise RefMismatchError(
                f"Requested ref {ref.chapter.title.identifier}/{ref.chapter.identifier}/{ref.identifier!r} "
                f"does not match citation's title/chapter {exp_title}/{exp_chapter}."
            )
        parsed = ParsedDocument(
            raw_citation=rec.citation,
            heading=rec.heading,
            text=rec.text,
            amendment_notes=None,
            source_url=str(self._resolve_data_path()),
            retrieved_at=datetime.now(timezone.utc),
        )
        return self.normalize(parsed, ref)

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"GeorgiaAdapter.normalize cannot normalize a ref for state "
                f"{ref.state_code!r}; expected {self.state_code!r}."
            )
        # Exact identity: parsed raw_citation must equal requested identifier
        if parsed.raw_citation != ref.identifier.strip():
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match parsed "
                f"citation {parsed.raw_citation!r}."
            )
        return StatuteSection(
            ref=ref,
            citation=Citation(state_code=self.state_code, raw=parsed.raw_citation),
            heading=parsed.heading,
            text=parsed.text,
            status=StatuteStatus.UNKNOWN,
            amendment_notes=parsed.amendment_notes,
            source_url=parsed.source_url,
            retrieved_at=parsed.retrieved_at,
        )

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        if isinstance(ref, SectionRef):
            return (
                f"local-ga-ocga://GA/"
                f"{ref.chapter.title.identifier}/{ref.chapter.identifier}/{ref.identifier}"
            )
        if isinstance(ref, ChapterRef):
            return (
                f"local-ga-ocga://GA/"
                f"{ref.title.identifier}/{ref.identifier}"
            )
        if isinstance(ref, TitleRef):
            return f"local-ga-ocga://GA/{ref.identifier}"
        raise UnsupportedRefError(
            f"GeorgiaAdapter.build_url does not support refs of type {type(ref).__name__!r}."
        )
