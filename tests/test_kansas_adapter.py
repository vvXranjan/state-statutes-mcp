"""Tests for KansasAdapter.

Kansas is a JSON-consuming adapter (the official Kansas Legislature API at
kslegislature.gov/api/v1/statutes/). Its hierarchy is Chapter -> Article ->
Section, which the adapter flattens onto the framework's TitleRef ->
ChapterRef -> SectionRef model (Chapter becomes the synthetic TitleRef).

These tests exercise the adapter's real fetch -> parse path against
**REAL captured Kansas API responses**: verbatim slices of the official
kslegislature.gov JSON captured live on Aug 15, 2026 and stored under
``tests/fixtures/ks_*``:

* ``ks_index.json`` -- the statutes index (87 chapters).
* ``ks_chapter_21.json`` -- the chapter-21 article listing (24 articles).
* ``ks_article_21_59.json`` -- the article 21-59 section listing (40
  sections, single page).
* ``ks_section_list_ch8_a1_p1.json`` / ``ks_section_list_ch8_a1_p2.json``
  -- the two paginated pages of article 1 of chapter 8 (219 sections),
  exercising the ``next_offset``/``offset`` pagination contract.
* ``ks_section_21-5903.json`` -- section 21-5903 (Perjury) with a long
  body and trailing History block.
* ``ks_section_8-1208.json`` -- section 8-1,208 (a comma-embedded section
  identifier, e.g. ``8-1%2C208`` in the URL).
* ``ks_section_404.json`` -- the HTTP 404 detail body for a nonexistent
  section.

All tests are fully offline: the real network boundary
(``urllib.request.urlopen`` as imported by the shared ``_fetch`` helper) is
mocked, never adapter internals.
"""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from _mock_network import mock_urlopen, mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.kansas.adapter import KansasAdapter
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

# --- REAL fixtures: verbatim slices of the official kslegislature.gov
# --- JSON API captured live on Aug 15, 2026. NOT synthetic.
FIXTURES = Path(__file__).parent / "fixtures"

REAL_INDEX_JSON = (FIXTURES / "ks_index.json").read_text(encoding="utf-8")
REAL_CH21_JSON = (FIXTURES / "ks_chapter_21.json").read_text(encoding="utf-8")
REAL_ART_21_59_JSON = (FIXTURES / "ks_article_21_59.json").read_text(encoding="utf-8")
REAL_SEC_21_5903_JSON = (FIXTURES / "ks_section_21-5903.json").read_text(
    encoding="utf-8"
)
REAL_SEC_8_1208_JSON = (FIXTURES / "ks_section_8-1208.json").read_text(
    encoding="utf-8"
)
REAL_P1_JSON = (FIXTURES / "ks_section_list_ch8_a1_p1.json").read_text(encoding="utf-8")
REAL_P2_JSON = (FIXTURES / "ks_section_list_ch8_a1_p2.json").read_text(encoding="utf-8")

BASE = "https://www.kslegislature.gov/api/v1/statutes"

INDEX_URL = f"{BASE}/"
CH21_URL = f"{BASE}/?chapter=21"
ART_21_59_URL = f"{BASE}/?chapter=21&article=59"
SEC_21_5903_URL = f"{BASE}/21-5903/"
SEC_8_1208_URL = f"{BASE}/8-1%2C208/"
P1_URL = f"{BASE}/?chapter=8&article=1"
P2_URL = f"{BASE}/?chapter=8&article=1&offset=200"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _title_ref() -> TitleRef:
    return TitleRef(state_code="KS", identifier="21")


def _chapter_ref() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="59")


def _section_ref(section: str = "21-5903") -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert KansasAdapter.__abstractmethods__ == frozenset()
        adapter = KansasAdapter()
        assert adapter.state_code == "KS"
        assert adapter.state_name == "Kansas"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = KansasAdapter()

    def test_title_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_title_ref()) == "https://www.kslegislature.gov/api/v1/statutes/?chapter=21"
        )

    def test_chapter_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_chapter_ref())
            == "https://www.kslegislature.gov/api/v1/statutes/?chapter=21&article=59"
        )

    def test_section_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_section_ref())
            == "https://www.kslegislature.gov/api/v1/statutes/21-5903/"
        )

    def test_section_ref_with_comma_is_url_encoded(self) -> None:
        ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="KS", identifier="8"), identifier="1"
            ),
            identifier="8-1,208",
        )
        assert (
            self.adapter.build_url(ref)
            == "https://www.kslegislature.gov/api/v1/statutes/8-1%2C208/"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestDiscovery:
    def setup_method(self) -> None:
        self.adapter = KansasAdapter()

    def test_list_titles(self) -> None:
        with mock_urlopen_serving({INDEX_URL: REAL_INDEX_JSON}):
            titles = self.adapter.list_titles()

        assert len(titles) == 87
        assert titles[0].identifier == "1"
        assert titles[-1].identifier == "97"
        # Chapter captions are always empty in the verified response, so
        # names fall back to the identifier.
        assert titles[0].name == "1"
        assert all(n.level == HierarchyLevel.TITLE for n in titles)
        assert all(n.ref.state_code == "KS" for n in titles)

    def test_list_titles_no_results_raises(self) -> None:
        with mock_urlopen(json.dumps({"count": 0})):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_titles_non_object_raises(self) -> None:
        with mock_urlopen("[]"):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_chapters(self) -> None:
        with mock_urlopen_serving({CH21_URL: REAL_CH21_JSON}):
            chapters = self.adapter.list_chapters(_title_ref())

        assert len(chapters) == 24
        assert chapters[0].identifier == "9"
        assert chapters[-1].identifier == "69"
        assert chapters[0].name == "9"
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)
        assert all(n.ref.title == _title_ref() for n in chapters)

    def test_list_chapters_no_results_raises(self) -> None:
        with mock_urlopen(json.dumps({"chapter": 21, "count": 0, "results": []})):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(_title_ref())

    def test_list_chapters_missing_results_raises(self) -> None:
        with mock_urlopen(json.dumps({"chapter": 21, "count": 0})):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(_title_ref())

    def test_list_sections(self) -> None:
        with mock_urlopen_serving({ART_21_59_URL: REAL_ART_21_59_JSON}):
            sections = self.adapter.list_sections(_chapter_ref())

        assert len(sections) == 40
        assert sections[0].identifier == "21-5901"
        assert "21-5903" in [s.identifier for s in sections]
        perjury = next(s for s in sections if s.identifier == "21-5903")
        assert perjury.name == "Perjury."
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == _chapter_ref() for n in sections)

    def test_list_sections_paginates_across_pages(self) -> None:
        chapter_ref = ChapterRef(
            title=TitleRef(state_code="KS", identifier="8"), identifier="1"
        )
        served = {P1_URL: REAL_P1_JSON, P2_URL: REAL_P2_JSON}
        with mock_urlopen_serving(served):
            sections = self.adapter.list_sections(chapter_ref)

        # Page 1 has 200 results (next_offset=200); page 2 has the
        # remaining 19 (next_offset=null): 219 total.
        assert len(sections) == 219
        identifiers = [s.identifier for s in sections]
        assert "8-113a" in identifiers
        assert "8-1,208" in identifiers
        assert "8-1,219" in identifiers

    def test_list_sections_no_results_raises(self) -> None:
        with mock_urlopen(json.dumps({"chapter": 21, "article": 59, "results": []})):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_sections(_chapter_ref())


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = KansasAdapter()

    def test_full_retrieval_citation_heading_body_history(self) -> None:
        with mock_urlopen_serving({SEC_21_5903_URL: REAL_SEC_21_5903_JSON}):
            section = self.adapter.retrieve_section(_section_ref())

        assert section.citation.raw == "Kan. Stat. Ann. § 21-5903"
        assert section.citation.state_code == "KS"
        assert section.ref == _section_ref()
        assert section.heading == "Perjury."
        assert section.text.startswith("(a) Perjury is intentionally and falsely:")
        assert section.text.endswith("trial of a felony charge.")
        assert section.amendment_notes == (
            "History: L. 2010, ch. 136, § 128; L. 2013, ch. 3, § 1; L. 2018, "
            "ch. 116, § 6; July 1."
        )
        assert section.status.value == "unknown"
        assert section.source_url == SEC_21_5903_URL
        assert section.retrieved_at is not None

    def test_comma_section_retrieval(self) -> None:
        ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="KS", identifier="8"), identifier="1"
            ),
            identifier="8-1,208",
        )
        with mock_urlopen_serving({SEC_8_1208_URL: REAL_SEC_8_1208_JSON}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Kan. Stat. Ann. § 8-1,208"
        assert section.ref == ref
        assert (
            section.heading
            == "Daughters of the American revolution license plate; requirements."
        )
        assert section.text.startswith("(a) On and after January 1, 2023")
        assert section.amendment_notes == "History: L. 2022, ch. 57, § 5; July 1."

    def test_section_mismatch_raises_ref_mismatch_error(self) -> None:
        payload = json.loads(REAL_SEC_21_5903_JSON)
        payload["section"] = "21-9999"
        with mock_urlopen_serving({SEC_21_5903_URL: json.dumps(payload)}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(_section_ref())

    def test_chapter_mismatch_raises_ref_mismatch_error(self) -> None:
        payload = json.loads(REAL_SEC_21_5903_JSON)
        payload["chapter"] = "20"
        with mock_urlopen_serving({SEC_21_5903_URL: json.dumps(payload)}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(_section_ref())

    def test_404_maps_to_ref_not_found(self) -> None:
        with mock_urlopen_error(_http_error(SEC_21_5903_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                self.adapter.retrieve_section(_section_ref())

    def test_network_failure_raises_adapter_unavailable_error(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(_section_ref())

    def test_malformed_json_raises_adapter_unavailable_error(self) -> None:
        with mock_urlopen("this is not json"):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(_section_ref())

    def test_missing_text_raises_normalization_error(self) -> None:
        payload = json.loads(REAL_SEC_21_5903_JSON)
        del payload["text"]
        with mock_urlopen_serving({SEC_21_5903_URL: json.dumps(payload)}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(_section_ref())

    def test_citation_prefix_mismatch_raises_normalization_error(self) -> None:
        payload = json.loads(REAL_SEC_21_5903_JSON)
        payload["text"] = payload["text"].replace(
            "21-5903. ", "21-9999. ", 1
        )
        with mock_urlopen_serving({SEC_21_5903_URL: json.dumps(payload)}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(_section_ref())


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = KansasAdapter()

    def test_normalize_success(self) -> None:
        ref = _section_ref()
        parsed = ParsedDocument(
            raw_citation="Kan. Stat. Ann. § 21-5903",
            heading="Perjury.",
            text="(a) Perjury is intentionally and falsely:...",
            amendment_notes="History: L. 2010, ch. 136, § 128; July 1.",
            source_url=SEC_21_5903_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "Kan. Stat. Ann. § 21-5903"
        assert section.citation.state_code == "KS"
        assert section.heading == "Perjury."
        assert section.text == "(a) Perjury is intentionally and falsely:..."
        assert section.amendment_notes == "History: L. 2010, ch. 136, § 128; July 1."
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="WA", identifier="49"),
                identifier="60",
            ),
            identifier="49.60.010",
        )
        parsed = ParsedDocument(raw_citation="Kan. Stat. Ann. § 21-5903", text="...")
        with pytest.raises(NormalizationError):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _section_ref()
        parsed = ParsedDocument(
            raw_citation="Kan. Stat. Ann. § 21-9999", text="Some other section."
        )
        with pytest.raises(RefMismatchError):
            self.adapter.normalize(parsed, ref)
