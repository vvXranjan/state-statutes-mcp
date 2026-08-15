"""Tests for NorthDakotaAdapter.

North Dakota is a bulk-JSON adapter: the official North Dakota Century
Code is exposed as ONE unpaginated JSON document at
``https://ndlegis.gov/api/data/century_code.json`` (titles -> chapters ->
sections). Every discovery and retrieval call reads from that single
fetched document.

These tests exercise the adapter's real fetch -> parse path against a
**REAL captured North Dakota response**: a trimmed copy of the official
ndlegis.gov bulk JSON captured live on Aug 15, 2026 and stored under
``tests/fixtures/nd_century_code_trimmed.json``. The trimmed fixture
preserves records verbatim from the full ~70 MB capture and keeps the real
``last_updated`` value:

* titles ``1`` (chapters ``01``, ``08``), ``4.1`` (chapters ``01``, ``89``),
  ``30.1`` (chapter ``04``), and ``2`` (chapter ``01``, repealed with zero
  sections).
* sections ``1-01-01`` (clean text), ``4.1-01-17`` (PDF-artifact text with
  an ``<ol>`` ``html``), and ``30.1-04-08`` (a Reserved section with empty
  ``text``/``html``).

All tests are fully offline: the real network boundary
(``urllib.request.urlopen`` as imported by the shared ``_fetch`` helper) is
mocked, never adapter internals.
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from _mock_network import mock_urlopen, mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.north_dakota.adapter import NorthDakotaAdapter
from state_statutes_mcp.core.exceptions import (
    AdapterUnavailableError,
    NormalizationError,
    RefMismatchError,
    RefNotFoundError,
    UnsupportedRefError,
)
from state_statutes_mcp.models.documents import ParsedDocument
from state_statutes_mcp.models.hierarchy import HierarchyLevel
from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef

# --- REAL fixture: a trimmed copy of the official ndlegis.gov bulk JSON
# --- captured live on Aug 15, 2026. Records are verbatim. NOT synthetic.
FIXTURES = Path(__file__).parent / "fixtures"
REAL_BULK_JSON = (FIXTURES / "nd_century_code_trimmed.json").read_text(
    encoding="utf-8"
)

BULK_URL = "https://ndlegis.gov/api/data/century_code.json"


def _title_ref(identifier: str = "1") -> TitleRef:
    return TitleRef(state_code="ND", identifier=identifier)


def _chapter_ref(chapter: str = "01", title: str = "1") -> ChapterRef:
    return ChapterRef(title=_title_ref(title), identifier=chapter)


def _section_ref(section: str = "1-01-01") -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert NorthDakotaAdapter.__abstractmethods__ == frozenset()
        adapter = NorthDakotaAdapter()
        assert adapter.state_code == "ND"
        assert adapter.state_name == "North Dakota"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = NorthDakotaAdapter()

    def test_all_ref_levels_return_bulk_url(self) -> None:
        # North Dakota exposes one bulk document; every level is
        # retrievable from it, so build_url returns it for all ref types.
        assert self.adapter.build_url(_title_ref()) == BULK_URL
        assert self.adapter.build_url(_chapter_ref()) == BULK_URL
        assert self.adapter.build_url(_section_ref()) == BULK_URL

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestDiscovery:
    def setup_method(self) -> None:
        self.adapter = NorthDakotaAdapter()

    def test_list_titles(self) -> None:
        with mock_urlopen_serving({BULK_URL: REAL_BULK_JSON}):
            titles = self.adapter.list_titles()

        assert [n.identifier for n in titles] == ["1", "2", "4.1", "30.1"]
        assert [n.name for n in titles] == [
            "General Provisions",
            "Aeronautics",
            "Agriculture",
            "Uniform Probate Code",
        ]
        assert all(n.level == HierarchyLevel.TITLE for n in titles)
        assert all(n.ref.state_code == "ND" for n in titles)

    def test_list_titles_non_object_raises(self) -> None:
        with mock_urlopen("[]"):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_titles_missing_titles_map_raises(self) -> None:
        with mock_urlopen(json.dumps({"last_updated": "2026-01-01"})):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_chapters(self) -> None:
        with mock_urlopen_serving({BULK_URL: REAL_BULK_JSON}):
            chapters = self.adapter.list_chapters(_title_ref("4.1"))

        assert [n.identifier for n in chapters] == ["01", "89"]
        assert [n.name for n in chapters] == [
            "Agriculture Commissioner",
            "Swine Health Improvement Plan",
        ]
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)

    def test_list_chapters_missing_title_raises_ref_not_found(self) -> None:
        with mock_urlopen_serving({BULK_URL: REAL_BULK_JSON}):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_chapters(_title_ref("999"))

    def test_list_chapters_title_without_chapters_map_raises(self) -> None:
        payload = json.loads(REAL_BULK_JSON)
        del payload["titles"]["1"]["chapters"]
        with mock_urlopen_serving({BULK_URL: json.dumps(payload)}):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(_title_ref("1"))

    def test_list_sections(self) -> None:
        with mock_urlopen_serving({BULK_URL: REAL_BULK_JSON}):
            sections = self.adapter.list_sections(_chapter_ref())

        assert [n.identifier for n in sections] == ["1-01-01", "1-01-26", "1-01-51"]
        assert [n.name for n in sections] == [
            "This act - How referred to",
            "False notice cannot become valid",
            "Qualified elector defined",
        ]
        assert all(n.level == HierarchyLevel.SECTION for n in sections)

    def test_list_sections_repealed_chapter_returns_empty(self) -> None:
        # Title 2, chapter 01 is repealed with zero sections (VERIFIED).
        # It is a valid, present chapter, so an empty tuple is returned.
        with mock_urlopen_serving({BULK_URL: REAL_BULK_JSON}):
            sections = self.adapter.list_sections(_chapter_ref(chapter="01", title="2"))

        assert sections == ()

    def test_list_sections_missing_title_raises_ref_not_found(self) -> None:
        with mock_urlopen_serving({BULK_URL: REAL_BULK_JSON}):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_sections(_chapter_ref(chapter="01", title="999"))

    def test_list_sections_missing_chapter_raises_ref_not_found(self) -> None:
        with mock_urlopen_serving({BULK_URL: REAL_BULK_JSON}):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_sections(_chapter_ref(chapter="99"))


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = NorthDakotaAdapter()

    def test_full_retrieval_citation_heading_body(self) -> None:
        with mock_urlopen_serving({BULK_URL: REAL_BULK_JSON}):
            section = self.adapter.retrieve_section(_section_ref())

        assert section.citation.raw == "N.D.C.C. § 1-01-01"
        assert section.citation.state_code == "ND"
        assert section.ref == _section_ref()
        assert section.heading == "This act - How referred to"
        assert section.text.startswith(
            "This revision, whenever cited, enumerated, referred to, or amended"
        )
        assert section.amendment_notes is None
        assert section.status.value == "unknown"
        assert section.source_url == BULK_URL
        assert section.retrieved_at is not None

    def test_dotted_title_section_retrieval(self) -> None:
        ref = _section_ref("4.1-01-17")
        ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="ND", identifier="4.1"), identifier="01"
            ),
            identifier="4.1-01-17",
        )
        with mock_urlopen_serving({BULK_URL: REAL_BULK_JSON}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "N.D.C.C. § 4.1-01-17"
        assert section.heading == (
            "Pipeline restoration and reclamation oversight program - Generally"
        )
        # The plain text field preserves the PDF-extraction artifacts
        # (double spaces, inline numbering) verbatim.
        assert section.text.startswith("1.The  commissioner  shall  establish")

    def test_reserved_section_raises_normalization_error(self) -> None:
        ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="ND", identifier="30.1"), identifier="04"
            ),
            identifier="30.1-04-08",
        )
        with mock_urlopen_serving({BULK_URL: REAL_BULK_JSON}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)

    def test_missing_title_raises_ref_not_found(self) -> None:
        ref = _section_ref("1-01-01")
        ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="ND", identifier="999"), identifier="01"
            ),
            identifier="999-01-01",
        )
        with mock_urlopen_serving({BULK_URL: REAL_BULK_JSON}):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(ref)

    def test_missing_chapter_raises_ref_not_found(self) -> None:
        ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="ND", identifier="1"), identifier="99"
            ),
            identifier="1-99-01",
        )
        with mock_urlopen_serving({BULK_URL: REAL_BULK_JSON}):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(ref)

    def test_missing_section_raises_ref_not_found(self) -> None:
        ref = _section_ref("1-01-99")
        with mock_urlopen_serving({BULK_URL: REAL_BULK_JSON}):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(ref)

    def test_title_mismatch_raises_ref_mismatch_error(self) -> None:
        payload = json.loads(REAL_BULK_JSON)
        payload["titles"]["1"]["title_num"] = "99"
        with mock_urlopen_serving({BULK_URL: json.dumps(payload)}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(_section_ref())

    def test_chapter_mismatch_raises_ref_mismatch_error(self) -> None:
        payload = json.loads(REAL_BULK_JSON)
        payload["titles"]["1"]["chapters"]["01"]["chapter_num"] = "99"
        with mock_urlopen_serving({BULK_URL: json.dumps(payload)}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(_section_ref())

    def test_section_mismatch_raises_ref_mismatch_error(self) -> None:
        payload = json.loads(REAL_BULK_JSON)
        payload["titles"]["1"]["chapters"]["01"]["sections"]["01"]["id"] = "1-01-99"
        with mock_urlopen_serving({BULK_URL: json.dumps(payload)}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(_section_ref())

    def test_network_failure_raises_adapter_unavailable_error(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(_section_ref())

    def test_malformed_json_raises_adapter_unavailable_error(self) -> None:
        with mock_urlopen("this is not json"):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(_section_ref())


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = NorthDakotaAdapter()

    def test_normalize_success(self) -> None:
        ref = _section_ref()
        parsed = ParsedDocument(
            raw_citation="N.D.C.C. § 1-01-01",
            heading="This act - How referred to",
            text="This revision, whenever cited, enumerated, referred to, or amended...",
            source_url=BULK_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "N.D.C.C. § 1-01-01"
        assert section.citation.state_code == "ND"
        assert section.heading == "This act - How referred to"
        assert section.text == "This revision, whenever cited, enumerated, referred to, or amended..."
        assert section.amendment_notes is None
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="WA", identifier="49"),
                identifier="60",
            ),
            identifier="49.60.010",
        )
        parsed = ParsedDocument(raw_citation="N.D.C.C. § 1-01-01", text="...")
        with pytest.raises(NormalizationError):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _section_ref()
        parsed = ParsedDocument(
            raw_citation="N.D.C.C. § 1-01-99", text="Some other section."
        )
        with pytest.raises(RefMismatchError):
            self.adapter.normalize(parsed, ref)
