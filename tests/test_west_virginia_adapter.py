"""Tests for WestVirginiaAdapter.

West Virginia is a server-rendered HTML source (the official West
Virginia Legislature publication of the West Virginia Code at
code.wvlegislature.gov). The code has NO title level: its Chapter ->
Article -> Section hierarchy is mapped onto the framework's Title ->
Chapter -> Section model (Texas precedent), so ``TitleRef`` holds the WV
chapter (``"11"``), ``ChapterRef`` the WV article (``"21"``), and
``SectionRef`` the full dotted section (``"11-21-12"``). Identifiers match
the URL path exactly (lettered suffixes render uppercase in hrefs, e.g.
``"11-21-3A"``).

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against **REAL captured West Virginia HTML**: verbatim
slices of the official code.wvlegislature.gov pages, captured via the
Wayback Machine on Aug 14-15, 2026 and stored under
``tests/fixtures/west_virginia_*``:

* ``west_virginia_home.html`` -- the home page's chapter ``<select>``
  dropdown (139 chapter options).
* ``west_virginia_chapter11.html`` -- the Chapter 11 page (102 article
  links).
* ``west_virginia_article1121.html`` -- the Chapter 11 / Article 21 page
  (143 section links, including lettered ``11-21-3A``).
* ``west_virginia_section112112.html`` -- section 11-21-12 "West Virginia
  adjusted gross income of resident individual".

All tests are fully offline: the real network boundary
(``urllib.request.urlopen`` as imported by the shared ``_fetch`` helper) is
mocked, never adapter internals.
"""

from __future__ import annotations

import io
import urllib.error
from pathlib import Path

import pytest

from _mock_network import mock_urlopen, mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.west_virginia.adapter import WestVirginiaAdapter
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

# --- REAL fixtures: verbatim slices of the official code.wvlegislature.gov
# --- pages captured via the Wayback Machine on Aug 14-15, 2026. NOT synthetic.
FIXTURES = Path(__file__).parent / "fixtures"

REAL_HOME_HTML = (FIXTURES / "west_virginia_home.html").read_text(encoding="utf-8")
REAL_CH11_HTML = (FIXTURES / "west_virginia_chapter11.html").read_text(
    encoding="utf-8"
)
REAL_ART1121_HTML = (FIXTURES / "west_virginia_article1121.html").read_text(
    encoding="utf-8"
)
REAL_SEC112112_HTML = (FIXTURES / "west_virginia_section112112.html").read_text(
    encoding="utf-8"
)

BASE = "https://code.wvlegislature.gov"

HOME_URL = f"{BASE}/"
CH11_URL = f"{BASE}/11/"
ART1121_URL = f"{BASE}/11-21/"
SEC112112_URL = f"{BASE}/11-21-12/"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _title11_ref() -> TitleRef:
    return TitleRef(state_code="WV", identifier="11")


def _article21_ref() -> ChapterRef:
    return ChapterRef(title=_title11_ref(), identifier="21")


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_article21_ref(), identifier=section)


def _serve_all() -> dict[str, str]:
    return {
        HOME_URL: REAL_HOME_HTML,
        CH11_URL: REAL_CH11_HTML,
        ART1121_URL: REAL_ART1121_HTML,
        SEC112112_URL: REAL_SEC112112_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert WestVirginiaAdapter.__abstractmethods__ == frozenset()
        adapter = WestVirginiaAdapter()
        assert adapter.state_code == "WV"
        assert adapter.state_name == "West Virginia"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = WestVirginiaAdapter()

    def test_title_ref_url_chapter_page(self) -> None:
        # A WV chapter maps onto TitleRef; build_url returns the chapter
        # page (article listing).
        assert self.adapter.build_url(_title11_ref()) == (
            "https://code.wvlegislature.gov/11/"
        )

    def test_chapter_ref_url_article_page(self) -> None:
        # A WV article maps onto ChapterRef; build_url returns the article
        # page (section listing).
        assert self.adapter.build_url(_article21_ref()) == (
            "https://code.wvlegislature.gov/11-21/"
        )

    def test_section_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("11-21-12"))
            == "https://code.wvlegislature.gov/11-21-12/"
        )

    def test_lettered_section_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("11-21-3A"))
            == "https://code.wvlegislature.gov/11-21-3A/"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestDiscovery:
    def setup_method(self) -> None:
        self.adapter = WestVirginiaAdapter()

    def test_list_titles_real_fixture(self) -> None:
        with mock_urlopen_serving({HOME_URL: REAL_HOME_HTML}):
            titles = self.adapter.list_titles()

        identifiers = [n.identifier for n in titles]
        assert len(identifiers) == 139
        assert identifiers[0] == "1"
        assert "11" in identifiers
        assert "5A" in identifiers
        assert "49A" in identifiers
        assert "64" in identifiers
        assert all(n.level == HierarchyLevel.TITLE for n in titles)
        assert all(n.ref.state_code == "WV" for n in titles)

    def test_list_titles_names(self) -> None:
        with mock_urlopen_serving({HOME_URL: REAL_HOME_HTML}):
            titles = self.adapter.list_titles()
        by_id = {n.identifier: n.name for n in titles}
        assert by_id["1"] == "THE STATE AND ITS SUBDIVISIONS."
        assert by_id["11"] == "TAXATION."
        assert by_id["5A"] == "DEPARTMENT OF ADMINISTRATION."

    def test_list_titles_sorted_numerically(self) -> None:
        with mock_urlopen_serving({HOME_URL: REAL_HOME_HTML}):
            titles = self.adapter.list_titles()
        ids = [n.identifier for n in titles]
        # 5A (numeric prefix 5) sorts before 6, after 5; 49A before 50.
        assert ids.index("5A") < ids.index("6")
        assert ids.index("49A") < ids.index("50")
        assert ids.index("11") < ids.index("12")

    def test_list_titles_no_options_raises(self) -> None:
        with mock_urlopen("<html><body>no chapters here</body></html>"):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_titles_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_chapters_real_fixture(self) -> None:
        with mock_urlopen_serving({CH11_URL: REAL_CH11_HTML}):
            chapters = self.adapter.list_chapters(_title11_ref())

        assert len(chapters) == 102
        assert [n.identifier for n in chapters][:4] == ["1", "1A", "1B", "1C"]
        assert [n.name for n in chapters][:4] == [
            "SUPERVISION.",
            "APPRAISAL OF PROPERTY.",
            "ADDITIONAL REVIEW OF PROPERTY APPRAISALS; IMPLEMENTATION.",
            "FAIR AND EQUITABLE PROPERTY VALUATION.",
        ]
        assert "21" in [n.identifier for n in chapters]
        assert [n.identifier for n in chapters][-1] == "28"
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)
        assert all(n.ref.title == _title11_ref() for n in chapters)

    def test_list_chapters_unknown_title_raises_ref_not_found(self) -> None:
        title_ref = TitleRef(state_code="WV", identifier="99")
        url = f"{BASE}/99/"
        with mock_urlopen_serving({url: REAL_CH11_HTML}):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_chapters(title_ref)

    def test_list_chapters_404_raises_ref_not_found(self) -> None:
        title_ref = TitleRef(state_code="WV", identifier="99")
        url = f"{BASE}/99/"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_chapters(title_ref)

    def test_list_chapters_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(_title11_ref())

    def test_list_sections_real_fixture(self) -> None:
        with mock_urlopen_serving({ART1121_URL: REAL_ART1121_HTML}):
            sections = self.adapter.list_sections(_article21_ref())

        assert len(sections) == 143
        assert [n.identifier for n in sections][:4] == [
            "11-21-1",
            "11-21-2",
            "11-21-3",
            "11-21-3A",
        ]
        assert [n.name for n in sections][:4] == [
            "Legislative findings.",
            "Short title; arrangement and classification.",
            "Imposition of tax; persons subject to tax.",
            "Imposition of tax; persons subject to tax.",
        ]
        assert [n.identifier for n in sections][-1] == "11-21-97"
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == _article21_ref() for n in sections)

    def test_list_sections_lettered_names(self) -> None:
        with mock_urlopen_serving({ART1121_URL: REAL_ART1121_HTML}):
            sections = self.adapter.list_sections(_article21_ref())
        by_id = {n.identifier: n.name for n in sections}
        assert by_id["11-21-3A"] == "Imposition of tax; persons subject to tax."
        assert by_id["11-21-12A"] == (
            "Additional modification reducing federal adjusted gross income."
        )

    def test_list_sections_sorted_numerically(self) -> None:
        with mock_urlopen_serving({ART1121_URL: REAL_ART1121_HTML}):
            sections = self.adapter.list_sections(_article21_ref())
        ids = [n.identifier for n in sections]
        # Lettered 11-21-3A sorts right after 11-21-3, before 11-21-4.
        assert ids.index("11-21-3") < ids.index("11-21-3A") < ids.index("11-21-4")
        assert ids.index("11-21-11") < ids.index("11-21-12")

    def test_list_sections_unknown_chapter_raises_ref_not_found(self) -> None:
        chapter_ref = ChapterRef(title=_title11_ref(), identifier="99")
        url = f"{BASE}/11-99/"
        with mock_urlopen_serving({url: REAL_ART1121_HTML}):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_sections(chapter_ref)

    def test_list_sections_404_raises_ref_not_found(self) -> None:
        chapter_ref = ChapterRef(title=_title11_ref(), identifier="99")
        url = f"{BASE}/11-99/"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_sections(chapter_ref)


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = WestVirginiaAdapter()

    def test_section_full_retrieval(self) -> None:
        ref = _make_ref("11-21-12")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "W. Va. Code § 11-21-12"
        assert section.citation.state_code == "WV"
        assert section.ref == ref
        assert section.heading == "West Virginia adjusted gross income of resident individual."
        assert section.text.startswith("(a) General. — The West Virginia adjusted gross income")
        assert "(b) Modifications increasing federal adjusted gross income." in section.text
        assert "§11-21-12. " not in section.text
        assert section.status.value == "unknown"
        assert section.amendment_notes is None
        assert section.source_url == SEC112112_URL
        assert section.retrieved_at is not None

    def test_chapter_mismatch_raises_ref_mismatch_error(self) -> None:
        # Request article 1 under chapter 11 but the page's container
        # belongs to chapter 11 / article 21.
        foreign_ref = SectionRef(
            chapter=ChapterRef(title=_title11_ref(), identifier="1"),
            identifier="11-21-12",
        )
        with mock_urlopen_serving({SEC112112_URL: REAL_SEC112112_HTML}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(foreign_ref)

    def test_section_code_mismatch_raises_ref_mismatch_error(self) -> None:
        # Request section 11-21-11 but the page's data-s is '12'.
        foreign_ref = _make_ref("11-21-11")
        url = f"{BASE}/11-21-11/"
        with mock_urlopen_serving({url: REAL_SEC112112_HTML}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(foreign_ref)

    def test_missing_section_404_raises_ref_not_found(self) -> None:
        ref = _make_ref("11-21-999")
        url = f"{BASE}/11-21-999/"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable_error(self) -> None:
        ref = _make_ref("11-21-12")
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestParseEdgeCases:
    def setup_method(self) -> None:
        self.adapter = WestVirginiaAdapter()

    def test_missing_container_raises_normalization_error(self) -> None:
        ref = _make_ref("11-21-12")
        html = (
            "<html><body>"
            "<div class='sectiontext hid'><h4>§11-21-12. X.</h4><p>(a) body</p></div>"
            "</body></html>"
        )
        with mock_urlopen_serving({SEC112112_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)

    def test_missing_heading_raises_normalization_error(self) -> None:
        ref = _make_ref("11-21-12")
        html = (
            "<div id='chpsel-container' data-m='home' data-c='11' data-a='21' "
            "data-s='12'></div>"
            "<div class='sectiontext hid'>"
            "<p>(a) body</p>"
            "</div>"
        )
        with mock_urlopen_serving({SEC112112_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)

    def test_empty_body_raises_normalization_error(self) -> None:
        ref = _make_ref("11-21-12")
        html = (
            "<div id='chpsel-container' data-m='home' data-c='11' data-a='21' "
            "data-s='12'></div>"
            "<div class='sectiontext hid'><h4>§11-21-12. X.</h4></div>"
        )
        with mock_urlopen_serving({SEC112112_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = WestVirginiaAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("11-21-12")
        parsed = ParsedDocument(
            raw_citation="W. Va. Code § 11-21-12",
            heading="West Virginia adjusted gross income of resident individual.",
            text="(a) General. — The West Virginia adjusted gross income ...",
            source_url=SEC112112_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "W. Va. Code § 11-21-12"
        assert section.citation.state_code == "WV"
        assert section.heading == "West Virginia adjusted gross income of resident individual."
        assert section.text == "(a) General. — The West Virginia adjusted gross income ..."
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
        parsed = ParsedDocument(
            raw_citation="W. Va. Code § 11-21-12",
            text="Some text.",
        )
        with pytest.raises(NormalizationError):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("11-21-12")
        parsed = ParsedDocument(
            raw_citation="W. Va. Code § 11-21-1",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError):
            self.adapter.normalize(parsed, ref)
