"""NewJerseyAdapter: official New Jersey General and Permanent Statutes.

Source: the New Jersey Legislature bulk publication
``STATUTES-TEXT.zip`` from ``pub.njleg.state.nj.us`` (SHA-256 of the
acquired ZIP: ``400dfa2e806c7f47fc6c539c66f830b376a4121419428562fd51aa9d4429974d``).
The primary text dataset is ``STATUTES.TXT`` (ASCII, CRLF).

This adapter does not fetch over the network. Production must set
``NEW_JERSEY_STATUTES_TXT`` to the extracted ``STATUTES.TXT`` path (or
pass ``data_path`` to the constructor). Tests inject a small
repository-contained representative fixture — not the full official file.

Citation form is ``{title}:{chapter}-{section}`` with optional decimal
and lettered suffixes (e.g. ``39:4-98``, ``39:4-98.1``, ``39:4-97a``).
Titles may be lettered (``2A``, ``18A``). Header lines in the official
file start at column 0; continuation/body lines are indented. Lookup is
an exact map from citation key to one record.
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

_HEADER_RE = re.compile(rb"^(\d+[A-Za-z]?):(\d+[A-Za-z]?)-(\S+)")
_TITLE_SORT_RE = re.compile(r"^(\d+)([A-Za-z]*)$")
_CHAPTER_SORT_RE = re.compile(r"^(\d+)([A-Za-z]*)$")


class _SectionRec(NamedTuple):
    title_id: str
    chapter_id: str
    section_id: str
    citation: str
    heading: str
    text: str


def _sort_key(identifier: str) -> tuple[int, str]:
    match = _TITLE_SORT_RE.match(identifier)
    if match:
        return (int(match.group(1)), match.group(2) or "")
    return (10**9, identifier)


class NewJerseyAdapter(BaseStateAdapter):
    """Concrete adapter for New Jersey statutes from STATUTES.TXT."""

    def __init__(self, data_path: str | Path | None = None) -> None:
        self._data_path = Path(data_path) if data_path is not None else None
        self._index: dict[str, _SectionRec] | None = None
        self._titles: tuple[TocNode, ...] | None = None
        self._chapters_map: dict[str, tuple[str, ...]] | None = None
        self._sections_map: dict[tuple[str, str], tuple[str, ...]] | None = None

    @property
    def state_code(self) -> str:
        return "NJ"

    @property
    def state_name(self) -> str:
        return "New Jersey"

    def _resolve_data_path(self) -> Path:
        if self._data_path is not None:
            if self._data_path.is_file():
                return self._data_path
            raise AdapterUnavailableError(
                f"New Jersey STATUTES.TXT not found at {str(self._data_path)!r}."
            )
        env = os.environ.get("NEW_JERSEY_STATUTES_TXT", "").strip()
        if env:
            path = Path(env)
            if path.is_file():
                return path
            raise AdapterUnavailableError(
                f"NEW_JERSEY_STATUTES_TXT is set but is not a file: {env!r}."
            )
        raise AdapterUnavailableError(
            "New Jersey STATUTES.TXT is not configured. Set the "
            "NEW_JERSEY_STATUTES_TXT environment variable to the official "
            "STATUTES.TXT extracted from STATUTES-TEXT.zip, or pass data_path."
        )

    def _ensure_index(self) -> None:
        if self._index is not None:
            return
        self._index = self._build_index()
        self._titles = self._build_titles()
        self._chapters_map = self._build_chapters_map()
        self._sections_map = self._build_sections_map()

    def _build_index(self) -> dict[str, _SectionRec]:
        filepath = self._resolve_data_path()
        try:
            raw = filepath.read_bytes()
        except OSError as exc:
            raise AdapterUnavailableError(
                f"Could not read STATUTES.TXT at {str(filepath)!r}: {exc}"
            ) from exc

        raw_lines = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")
        index: dict[str, _SectionRec] = {}
        i = 0
        n = len(raw_lines)
        while i < n:
            line = raw_lines[i]
            match = _HEADER_RE.match(line)
            if match is None:
                i += 1
                continue
            token = line.split()[0].decode("ascii", errors="replace").rstrip(".")
            try:
                title_id, rest = token.split(":", 1)
                chapter_id, section_id = rest.split("-", 1)
            except ValueError:
                i += 1
                continue
            heading = line.decode("ascii", errors="replace").rstrip()
            body_parts: list[str] = []
            j = i + 1
            while j < n:
                nxt = raw_lines[j]
                if _HEADER_RE.match(nxt) is not None:
                    break
                body_parts.append(nxt.decode("ascii", errors="replace"))
                j += 1
            rec = _SectionRec(
                title_id=title_id,
                chapter_id=chapter_id,
                section_id=section_id.rstrip("."),
                citation=token,
                heading=heading,
                text="\n".join(body_parts).strip(),
            )
            if token not in index:
                index[token] = rec
            i = j
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
                    ref=TitleRef(state_code="NJ", identifier=rec.title_id),
                )
            )
        nodes.sort(key=lambda node: _sort_key(node.identifier))
        return tuple(nodes)

    def _build_chapters_map(self) -> dict[str, tuple[str, ...]]:
        assert self._index is not None
        mapping: dict[str, set[str]] = {}
        for rec in self._index.values():
            mapping.setdefault(rec.title_id, set()).add(rec.chapter_id)
        return {
            title: tuple(sorted(chapters, key=_sort_key))
            for title, chapters in mapping.items()
        }

    def _build_sections_map(self) -> dict[tuple[str, str], tuple[str, ...]]:
        assert self._index is not None
        mapping: dict[tuple[str, str], list[str]] = {}
        for rec in self._index.values():
            mapping.setdefault((rec.title_id, rec.chapter_id), []).append(rec.citation)
        return {
            key: tuple(sorted(set(cites), key=_sort_key))
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
        citation_key = ref.identifier.rstrip(".")
        rec = self._index.get(citation_key)
        if rec is None:
            raise RefNotFoundError(
                f"New Jersey section {citation_key!r} not found in STATUTES.TXT."
            )
        caption_parts = rec.heading.split(None, 1)
        caption = caption_parts[1].strip() if len(caption_parts) > 1 else None
        if not rec.text:
            raise NormalizationError(
                f"Section {citation_key!r} has no body text in the dataset."
            )
        parsed = ParsedDocument(
            raw_citation=rec.citation,
            heading=caption,
            text=rec.text,
            amendment_notes=None,
            source_url=str(self._resolve_data_path()),
            retrieved_at=datetime.now(timezone.utc),
        )
        return self.normalize(parsed, ref)

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"NewJerseyAdapter.normalize cannot normalize a ref for state "
                f"{ref.state_code!r}; expected {self.state_code!r}."
            )
        if ref.identifier.rstrip(".") not in parsed.raw_citation:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"citation found in the parsed document: {parsed.raw_citation!r}."
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
                f"local-nj-statutes://{ref.state_code}/"
                f"{ref.chapter.title.identifier}:{ref.chapter.identifier}:{ref.identifier}"
            )
        if isinstance(ref, ChapterRef):
            return (
                f"local-nj-statutes://{ref.state_code}/"
                f"{ref.title.identifier}:{ref.identifier}"
            )
        if isinstance(ref, TitleRef):
            return f"local-nj-statutes://{ref.state_code}/{ref.identifier}"
        raise UnsupportedRefError(
            f"NewJerseyAdapter.build_url does not support refs of type "
            f"{type(ref).__name__!r}."
        )
