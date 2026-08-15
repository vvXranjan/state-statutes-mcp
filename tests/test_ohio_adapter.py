"""Tests for OhioAdapter.

Ohio is a server-rendered HTML source (the official Ohio Laws publication
of the Ohio Revised Code at codes.ohio.gov). Three structural levels
(Title -> Chapter -> Section) map 1:1 onto the framework model; titles are
numbered 1-63 (odd only, 33 total); chapter numbers are the 4-digit prefix
of the section numbers in that title; section identifiers may carry a
decimal extension (``2901.011``).

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against **REAL captured Ohio HTML**: verbatim slices
of the official codes.ohio.gov pages, captured via a Wayback Machine
snapshot of the official host (timestamp 20260812050041, the live host
being unreachable from this environment) and stored under
``tests/fixtures/oh_*``:

* ``oh_orc_index.html`` -- the ORC index page title list (33 numbered
  titles plus an excluded unnumbered General Provisions entry).
* ``oh_title29.html`` -- the Title 29 page (36 chapters).
* ``oh_chapter2901.html`` -- the Chapter 2901 page (26 sections, including
  the decimal-extension ``2901.011``).
* ``oh_section_2901.01.html`` -- section 2901.01 "General provisions
  definitions." (with breadcrumbs, laws-body, laws-history version list).
* ``oh_section_2901.011.html`` -- section 2901.011 "Reagan Tokes Law." (the
  decimal-extension edge case).

All tests are fully offline: the real network boundary
(``urllib.request.urlopen`` as imported by the shared ``_fetch`` helper) is
mocked, never adapter internals.
"""

from __future__ import annotations

import io
import re
import urllib.error
from pathlib import Path

import pytest

from _mock_network import mock_urlopen, mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.ohio.adapter import OhioAdapter
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

# --- REAL fixtures: verbatim slices of the official Ohio Revised Code
# --- pages captured through a Wayback Machine snapshot of codes.ohio.gov
# --- (timestamp 20260812050041). NOT synthetic.
FIXTURES = Path(__file__).parent / "fixtures"

REAL_ORC_INDEX_HTML = (FIXTURES / "oh_orc_index.html").read_text(encoding="utf-8")
REAL_TITLE29_HTML = (FIXTURES / "oh_title29.html").read_text(encoding="utf-8")
REAL_CH2901_HTML = (FIXTURES / "oh_chapter2901.html").read_text(encoding="utf-8")
REAL_SEC2901_01_HTML = (FIXTURES / "oh_section_2901.01.html").read_text(
    encoding="utf-8"
)
REAL_SEC2901_011_HTML = (FIXTURES / "oh_section_2901.011.html").read_text(
    encoding="utf-8"
)

BASE = "https://codes.ohio.gov"

ORC_INDEX_URL = f"{BASE}/ohio-revised-code"
TITLE29_URL = f"{BASE}/ohio-revised-code/title-29"
CH2901_URL = f"{BASE}/ohio-revised-code/chapter-2901"
SEC2901_01_URL = f"{BASE}/ohio-revised-code/section-2901.01"
SEC2901_011_URL = f"{BASE}/ohio-revised-code/section-2901.011"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _title_ref() -> TitleRef:
    return TitleRef(state_code="OH", identifier="29")


def _chapter_ref() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="2901")


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


def _serve_all() -> dict[str, str]:
    return {
        ORC_INDEX_URL: REAL_ORC_INDEX_HTML,
        TITLE29_URL: REAL_TITLE29_HTML,
        CH2901_URL: REAL_CH2901_HTML,
        SEC2901_01_URL: REAL_SEC2901_01_HTML,
        SEC2901_011_URL: REAL_SEC2901_011_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert OhioAdapter.__abstractmethods__ == frozenset()
        adapter = OhioAdapter()
        assert adapter.state_code == "OH"
        assert adapter.state_name == "Ohio"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = OhioAdapter()

    def test_title_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_title_ref())
            == "https://codes.ohio.gov/ohio-revised-code/title-29"
        )

    def test_chapter_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_chapter_ref())
            == "https://codes.ohio.gov/ohio-revised-code/chapter-2901"
        )

    def test_section_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("2901.01"))
            == "https://codes.ohio.gov/ohio-revised-code/section-2901.01"
        )

    def test_section_ref_url_decimal_extension(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("2901.011"))
            == "https://codes.ohio.gov/ohio-revised-code/section-2901.011"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestDiscovery:
    def setup_method(self) -> None:
        self.adapter = OhioAdapter()

    def test_list_titles_real_fixture(self) -> None:
        with mock_urlopen_serving({ORC_INDEX_URL: REAL_ORC_INDEX_HTML}):
            titles = self.adapter.list_titles()

        identifiers = [n.identifier for n in titles]
        assert len(identifiers) == 33
        assert identifiers[:5] == ["1", "3", "5", "7", "9"]
        assert identifiers[-1] == "63"
        assert titles[0].name == "State Government"
        assert all(n.level == HierarchyLevel.TITLE for n in titles)
        assert all(n.ref.state_code == "OH" for n in titles)

    def test_list_titles_numeric_order(self) -> None:
        with mock_urlopen_serving({ORC_INDEX_URL: REAL_ORC_INDEX_HTML}):
            titles = self.adapter.list_titles()
        identifiers = [n.identifier for n in titles]
        assert identifiers == sorted(identifiers, key=int)

    def test_list_titles_excludes_general_provisions_entry(self) -> None:
        with mock_urlopen_serving({ORC_INDEX_URL: REAL_ORC_INDEX_HTML}):
            titles = self.adapter.list_titles()
        identifiers = [n.identifier for n in titles]
        # The unnumbered 'General Provisions' entry has no 'title-{N}' href
        # and must not be listed as a title.
        assert "General Provisions" not in identifiers

    def test_list_titles_no_title_links_raises(self) -> None:
        with mock_urlopen("<html><body>no titles here</body></html>"):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_titles_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_chapters_real_fixture(self) -> None:
        with mock_urlopen_serving({TITLE29_URL: REAL_TITLE29_HTML}):
            chapters = self.adapter.list_chapters(_title_ref())

        assert len(chapters) == 36
        assert [n.identifier for n in chapters][:3] == ["2901", "2903", "2905"]
        assert chapters[0].name == "General Provisions"
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)
        assert all(n.ref.title == _title_ref() for n in chapters)

    def test_list_chapters_404_raises_ref_not_found(self) -> None:
        title_ref = TitleRef(state_code="OH", identifier="999")
        url = "https://codes.ohio.gov/ohio-revised-code/title-999"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_chapters(title_ref)

    def test_list_chapters_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(_title_ref())

    def test_list_sections_real_fixture(self) -> None:
        with mock_urlopen_serving({CH2901_URL: REAL_CH2901_HTML}):
            sections = self.adapter.list_sections(_chapter_ref())

        assert len(sections) == 26
        assert [n.identifier for n in sections][:3] == ["2901.01", "2901.011", "2901.02"]
        assert sections[0].name == "General provisions definitions."
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == _chapter_ref() for n in sections)

    def test_list_sections_numeric_order(self) -> None:
        with mock_urlopen_serving({CH2901_URL: REAL_CH2901_HTML}):
            sections = self.adapter.list_sections(_chapter_ref())
        identifiers = [n.identifier for n in sections]

        def numeric_key(identifier: str) -> tuple[int, str]:
            leading = re.match(r"\d+", identifier)
            return (int(leading.group()) if leading else 0, identifier)

        assert identifiers == sorted(identifiers, key=numeric_key)
        assert identifiers[:3] == ["2901.01", "2901.011", "2901.02"]

    def test_list_sections_decimal_extension_identifier(self) -> None:
        with mock_urlopen_serving({CH2901_URL: REAL_CH2901_HTML}):
            sections = self.adapter.list_sections(_chapter_ref())
        by_id = {n.identifier: n.name for n in sections}
        assert by_id["2901.011"] == "Reagan Tokes Law."

    def test_list_sections_404_raises_ref_not_found(self) -> None:
        chapter_ref = ChapterRef(title=_title_ref(), identifier="2999")
        url = "https://codes.ohio.gov/ohio-revised-code/chapter-2999"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_sections(chapter_ref)

    def test_list_sections_no_links_raises(self) -> None:
        with mock_urlopen_serving({CH2901_URL: "<html><body>no sections</body></html>"}):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_sections(_chapter_ref())


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = OhioAdapter()

    def test_simple_section_full_retrieval(self) -> None:
        ref = _make_ref("2901.01")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Ohio Rev. Code § 2901.01"
        assert section.citation.state_code == "OH"
        assert section.ref == ref
        assert section.heading == "General provisions definitions."
        assert section.text.startswith("(A) As used in the Revised Code:")
        assert '"Force" means any violence' in section.text
        assert '"School bus" has the same meaning' in section.text
        assert "Effective: October 3, 2023" not in section.text
        assert "Latest Legislation:" not in section.text
        assert "Last updated" not in section.text
        assert "September 10, 2012" in section.amendment_notes
        assert "House Bill 487" in section.amendment_notes
        assert "April 6, 2017" in section.amendment_notes
        assert section.status.value == "unknown"
        assert section.source_url == SEC2901_01_URL
        assert section.retrieved_at is not None

    def test_decimal_extension_section(self) -> None:
        ref = _make_ref("2901.011")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Ohio Rev. Code § 2901.011"
        assert section.heading == "Reagan Tokes Law."
        assert section.text.strip() != ""
        assert section.status.value == "unknown"
        assert section.source_url == SEC2901_011_URL

    def test_title_mismatch_raises_ref_mismatch_error(self) -> None:
        # Request title 1 but the section page belongs to title 29.
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="OH", identifier="1"),
                identifier="2901",
            ),
            identifier="2901.01",
        )
        url = "https://codes.ohio.gov/ohio-revised-code/section-2901.01"
        with mock_urlopen_serving({url: REAL_SEC2901_01_HTML}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(foreign_ref)

    def test_chapter_mismatch_raises_ref_mismatch_error(self) -> None:
        # Request chapter 2903 but the section page belongs to chapter 2901.
        foreign_ref = SectionRef(
            chapter=ChapterRef(title=_title_ref(), identifier="2903"),
            identifier="2901.01",
        )
        with mock_urlopen_serving({SEC2901_01_URL: REAL_SEC2901_01_HTML}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(foreign_ref)

    def test_section_id_mismatch_raises_ref_mismatch_error(self) -> None:
        # Request 2901.02 but the page's h1 is 2901.01.
        foreign_ref = _make_ref("2901.02")
        url = "https://codes.ohio.gov/ohio-revised-code/section-2901.02"
        with mock_urlopen_serving({url: REAL_SEC2901_01_HTML}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(foreign_ref)

    def test_missing_section_404_raises_ref_not_found(self) -> None:
        ref = _make_ref("9999.99")
        url = "https://codes.ohio.gov/ohio-revised-code/section-9999.99"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable_error(self) -> None:
        ref = _make_ref("2901.01")
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestParseEdgeCases:
    def setup_method(self) -> None:
        self.adapter = OhioAdapter()

    def test_empty_body_raises_normalization_error(self) -> None:
        ref = _make_ref("2901.01")
        html = (
            "<html><body>"
            '<div class="breadcrumbs">'
            '<a href="/ohio-revised-code/title-29">Title 29</a>'
            '<a href="/ohio-revised-code/chapter-2901">Chapter 2901</a>'
            "</div>"
            "<h1>Section 2901.01 <span class='codes-separator'>|</span> Empty</h1>"
            '<section class="laws-body"><span></span></section>'
            "</body></html>"
        )
        with mock_urlopen_serving({SEC2901_01_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)

    def test_missing_heading_raises_normalization_error(self) -> None:
        ref = _make_ref("2901.01")
        html = (
            "<html><body>"
            '<div class="breadcrumbs">'
            '<a href="/ohio-revised-code/title-29">Title 29</a>'
            '<a href="/ohio-revised-code/chapter-2901">Chapter 2901</a>'
            "</div>"
            '<section class="laws-body"><span><p>body</p></span></section>'
            "</body></html>"
        )
        with mock_urlopen_serving({SEC2901_01_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)

    def test_missing_title_breadcrumb_raises_normalization_error(self) -> None:
        ref = _make_ref("2901.01")
        html = (
            "<html><body>"
            '<div class="breadcrumbs">'
            '<a href="/ohio-revised-code/chapter-2901">Chapter 2901</a>'
            "</div>"
            "<h1>Section 2901.01 <span class='codes-separator'>|</span> Heading</h1>"
            '<section class="laws-body"><span><p>body</p></span></section>'
            "</body></html>"
        )
        with mock_urlopen_serving({SEC2901_01_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = OhioAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("2901.01")
        parsed = ParsedDocument(
            raw_citation="Ohio Rev. Code § 2901.01",
            heading="General provisions definitions.",
            text="(A) As used in the Revised Code ...",
            amendment_notes="September 10, 2012 – House Bill 487 - 129th General Assembly",
            source_url=SEC2901_01_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "Ohio Rev. Code § 2901.01"
        assert section.citation.state_code == "OH"
        assert section.heading == "General provisions definitions."
        assert section.text == "(A) As used in the Revised Code ..."
        assert (
            section.amendment_notes
            == "September 10, 2012 – House Bill 487 - 129th General Assembly"
        )
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="WA", identifier="49"),
                identifier="60",
            ),
            identifier="49.60.010",
        )
        parsed = ParsedDocument(
            raw_citation="Ohio Rev. Code § 2901.01",
            text="Some text.",
        )
        with pytest.raises(NormalizationError):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("2901.01")
        parsed = ParsedDocument(
            raw_citation="Ohio Rev. Code § 2901.02",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError):
            self.adapter.normalize(parsed, ref)
