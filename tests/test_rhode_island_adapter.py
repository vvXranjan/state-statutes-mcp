"""Tests for RhodeIslandAdapter.

Rhode Island is a server-rendered HTML source (the official Rhode Island
General Assembly publication of the General Laws at
webserver.rilegislature.gov). Three structural levels (Title -> Chapter ->
Section) map 1:1 onto the framework model; titles include lettered (``6A``)
and decimal (``40.1``) identifiers; chapter identifiers are the full
``{t}-{c}`` directory form (``43-3``, ``6A-2.1``); section identifiers are
the full ``{t}-{c}-{s}`` citation form and may carry a decimal extension
(``43-3-3.1``).

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against **REAL captured Rhode Island HTML**: verbatim
slices of the official webserver.rilegislature.gov pages, captured via a
Wayback Machine snapshot of the official host (timestamp 20250401074949,
the live host being unreachable from this environment) and stored under
``tests/fixtures/ri_*``:

* ``ri_statutes.html`` -- the master Statutes page (49 titles including
  ``6A`` and ``40.1``).
* ``ri_title43_index.htm`` -- the Title 43 index page (4 chapters).
* ``ri_title6a_index.htm`` -- the Title 6A index page (13 chapters,
  including decimal ``6A-2.1``).
* ``ri_title40p1_index.htm`` -- the Title 40.1 index page (33 chapter rows,
  including empty-stub placeholders for repealed chapters).
* ``ri_ch43-3_index.htm`` -- the Chapter 43-3 index page (36 sections,
  including decimal ``43-3-3.1`` and repealed ``43-3-7``).
* ``ri_section_43-3-2.htm`` -- section 43-3-2 "Application of rules of
  construction." (a normal section with history).
* ``ri_section_43-3-7.htm`` -- section 43-3-7, a repealed section
  (heading ``Repealed.``, empty body).
* ``ri_section_43-3-3.1.htm`` -- section 43-3-3.1, the decimal-extension
  edge case.
* ``ri_section_40.1-1-1.htm`` -- section 40.1-1-1, a repealed-RANGE section
  (heading ``[Repealed.]``, empty body).

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

from state_statutes_mcp.adapters.rhode_island.adapter import RhodeIslandAdapter
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
from state_statutes_mcp.models.statute_section import StatuteStatus

# --- REAL fixtures: verbatim slices of the official Rhode Island General
# --- Laws pages captured through a Wayback Machine snapshot of
# --- webserver.rilegislature.gov (timestamp 20250401074949). NOT synthetic.
FIXTURES = Path(__file__).parent / "fixtures"

REAL_STATUTES_HTML = (FIXTURES / "ri_statutes.html").read_text(encoding="utf-8")
REAL_TITLE43_INDEX_HTML = (FIXTURES / "ri_title43_index.htm").read_text(
    encoding="utf-8"
)
REAL_TITLE6A_INDEX_HTML = (FIXTURES / "ri_title6a_index.htm").read_text(
    encoding="utf-8"
)
REAL_TITLE40P1_INDEX_HTML = (FIXTURES / "ri_title40p1_index.htm").read_text(
    encoding="utf-8"
)
REAL_CH43_3_INDEX_HTML = (FIXTURES / "ri_ch43-3_index.htm").read_text(
    encoding="utf-8"
)
REAL_SEC43_3_2_HTML = (FIXTURES / "ri_section_43-3-2.htm").read_text(
    encoding="utf-8"
)
REAL_SEC43_3_7_HTML = (FIXTURES / "ri_section_43-3-7.htm").read_text(
    encoding="utf-8"
)
REAL_SEC43_3_3_1_HTML = (FIXTURES / "ri_section_43-3-3.1.htm").read_text(
    encoding="utf-8"
)
REAL_SEC40_1_1_1_HTML = (FIXTURES / "ri_section_40.1-1-1.htm").read_text(
    encoding="utf-8"
)

BASE = "http://webserver.rilegislature.gov"

STATUTES_URL = f"{BASE}/Statutes/Statutes.html"
TITLE43_URL = f"{BASE}/Statutes/TITLE43/INDEX.HTM"
TITLE6A_URL = f"{BASE}/Statutes/TITLE6A/INDEX.HTM"
TITLE40P1_URL = f"{BASE}/Statutes/TITLE40.1/INDEX.HTM"
CH43_3_URL = f"{BASE}/Statutes/TITLE43/43-3/INDEX.htm"
SEC43_3_2_URL = f"{BASE}/Statutes/TITLE43/43-3/43-3-2.htm"
SEC43_3_7_URL = f"{BASE}/Statutes/TITLE43/43-3/43-3-7.htm"
SEC43_3_3_1_URL = f"{BASE}/Statutes/TITLE43/43-3/43-3-3.1.htm"
SEC40_1_1_1_URL = f"{BASE}/Statutes/TITLE40.1/40.1-1/40.1-1-1.htm"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _title_ref() -> TitleRef:
    return TitleRef(state_code="RI", identifier="43")


def _chapter_ref() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="43-3")


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


def _serve_all() -> dict[str, str]:
    return {
        STATUTES_URL: REAL_STATUTES_HTML,
        TITLE43_URL: REAL_TITLE43_INDEX_HTML,
        TITLE6A_URL: REAL_TITLE6A_INDEX_HTML,
        TITLE40P1_URL: REAL_TITLE40P1_INDEX_HTML,
        CH43_3_URL: REAL_CH43_3_INDEX_HTML,
        SEC43_3_2_URL: REAL_SEC43_3_2_HTML,
        SEC43_3_7_URL: REAL_SEC43_3_7_HTML,
        SEC43_3_3_1_URL: REAL_SEC43_3_3_1_HTML,
        SEC40_1_1_1_URL: REAL_SEC40_1_1_1_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert RhodeIslandAdapter.__abstractmethods__ == frozenset()
        adapter = RhodeIslandAdapter()
        assert adapter.state_code == "RI"
        assert adapter.state_name == "Rhode Island"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = RhodeIslandAdapter()

    def test_title_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_title_ref())
            == "http://webserver.rilegislature.gov/Statutes/TITLE43/INDEX.HTM"
        )

    def test_title_ref_url_lettered(self) -> None:
        ref = TitleRef(state_code="RI", identifier="6A")
        assert (
            self.adapter.build_url(ref)
            == "http://webserver.rilegislature.gov/Statutes/TITLE6A/INDEX.HTM"
        )

    def test_title_ref_url_decimal(self) -> None:
        ref = TitleRef(state_code="RI", identifier="40.1")
        assert (
            self.adapter.build_url(ref)
            == "http://webserver.rilegislature.gov/Statutes/TITLE40.1/INDEX.HTM"
        )

    def test_chapter_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_chapter_ref())
            == "http://webserver.rilegislature.gov/Statutes/TITLE43/43-3/INDEX.htm"
        )

    def test_chapter_ref_url_decimal(self) -> None:
        ref = ChapterRef(title=_title_ref(), identifier="43-3")
        assert (
            self.adapter.build_url(ref)
            == "http://webserver.rilegislature.gov/Statutes/TITLE43/43-3/INDEX.htm"
        )

    def test_section_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("43-3-2"))
            == "http://webserver.rilegislature.gov/Statutes/TITLE43/43-3/43-3-2.htm"
        )

    def test_section_ref_url_decimal_extension(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("43-3-3.1"))
            == "http://webserver.rilegislature.gov/Statutes/TITLE43/43-3/43-3-3.1.htm"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestDiscovery:
    def setup_method(self) -> None:
        self.adapter = RhodeIslandAdapter()

    def test_list_titles_real_fixture(self) -> None:
        with mock_urlopen_serving({STATUTES_URL: REAL_STATUTES_HTML}):
            titles = self.adapter.list_titles()

        identifiers = [n.identifier for n in titles]
        assert len(identifiers) == 49
        assert identifiers[:5] == ["1", "2", "3", "4", "5"]
        assert identifiers[-3:] == ["45", "46", "47"]
        assert titles[0].name == "Aeronautics"
        assert all(n.level == HierarchyLevel.TITLE for n in titles)
        assert all(n.ref.state_code == "RI" for n in titles)

    def test_list_titles_special_identifiers_present(self) -> None:
        with mock_urlopen_serving({STATUTES_URL: REAL_STATUTES_HTML}):
            titles = self.adapter.list_titles()
        by_id = {n.identifier: n.name for n in titles}
        assert "6A" in by_id
        assert "40.1" in by_id

    def test_list_titles_no_rows_raises(self) -> None:
        with mock_urlopen("<html><body>no titles here</body></html>"):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_titles_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_chapters_real_fixture(self) -> None:
        with mock_urlopen_serving({TITLE43_URL: REAL_TITLE43_INDEX_HTML}):
            chapters = self.adapter.list_chapters(_title_ref())

        assert len(chapters) == 4
        assert [n.identifier for n in chapters] == ["43-1", "43-2", "43-3", "43-4"]
        assert [n.name for n in chapters] == [
            "Action by Governor",
            "Publication and Distribution of Acts",
            "Construction and Effect of Statutes",
            "Effect of General Laws",
        ]
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)
        assert all(n.ref.title == _title_ref() for n in chapters)

    def test_list_chapters_lettered_title(self) -> None:
        title_ref = TitleRef(state_code="RI", identifier="6A")
        with mock_urlopen_serving({TITLE6A_URL: REAL_TITLE6A_INDEX_HTML}):
            chapters = self.adapter.list_chapters(title_ref)
        identifiers = [n.identifier for n in chapters]
        assert len(identifiers) == 13
        assert "6A-2.1" in identifiers
        assert "6A-4.1" in identifiers

    def test_list_chapters_decimal_title(self) -> None:
        title_ref = TitleRef(state_code="RI", identifier="40.1")
        with mock_urlopen_serving({TITLE40P1_URL: REAL_TITLE40P1_INDEX_HTML}):
            chapters = self.adapter.list_chapters(title_ref)
        identifiers = [n.identifier for n in chapters]
        # 33 chapter rows on the page, but the three empty-stub rows
        # (40.1-8.1, 40.1-11, 40.1-24.1) have no link text and are skipped.
        assert len(identifiers) == 30
        assert "40.1-1" in identifiers
        assert "40.1-1.1" in identifiers
        assert "40.1-8.1" not in identifiers
        assert "40.1-11" not in identifiers
        assert "40.1-24.1" not in identifiers

    def test_list_chapters_404_raises_ref_not_found(self) -> None:
        title_ref = TitleRef(state_code="RI", identifier="999")
        url = "http://webserver.rilegislature.gov/Statutes/TITLE999/INDEX.HTM"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_chapters(title_ref)

    def test_list_chapters_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(_title_ref())

    def test_list_sections_real_fixture(self) -> None:
        with mock_urlopen_serving({CH43_3_URL: REAL_CH43_3_INDEX_HTML}):
            sections = self.adapter.list_sections(_chapter_ref())

        assert len(sections) == 36
        assert [n.identifier for n in sections][:3] == ["43-3-1", "43-3-2", "43-3-3"]
        assert sections[0].name == "English statutes as common law."
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == _chapter_ref() for n in sections)

    def test_list_sections_decimal_extension_identifier(self) -> None:
        with mock_urlopen_serving({CH43_3_URL: REAL_CH43_3_INDEX_HTML}):
            sections = self.adapter.list_sections(_chapter_ref())
        by_id = {n.identifier: n.name for n in sections}
        assert by_id["43-3-3.1"] == "Gender of titles."
        assert by_id["43-3-22.1"] == (
            "Enlargement of statutes of limitation — Effect on actions not yet expired."
        )

    def test_list_sections_repealed_marker_preserved(self) -> None:
        with mock_urlopen_serving({CH43_3_URL: REAL_CH43_3_INDEX_HTML}):
            sections = self.adapter.list_sections(_chapter_ref())
        by_id = {n.identifier: n.name for n in sections}
        assert by_id["43-3-7"] == "Repealed."

    def test_list_sections_404_raises_ref_not_found(self) -> None:
        chapter_ref = ChapterRef(title=_title_ref(), identifier="43-99")
        url = "http://webserver.rilegislature.gov/Statutes/TITLE43/43-99/INDEX.htm"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_sections(chapter_ref)

    def test_list_sections_no_links_raises(self) -> None:
        with mock_urlopen_serving(
            {CH43_3_URL: "<html><body>no sections</body></html>"}
        ):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_sections(_chapter_ref())


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = RhodeIslandAdapter()

    def test_simple_section_full_retrieval(self) -> None:
        ref = _make_ref("43-3-2")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "R.I. Gen. Laws § 43-3-2"
        assert section.citation.state_code == "RI"
        assert section.ref == ref
        assert section.heading == "Application of rules of construction."
        assert section.text.startswith(
            "In the construction of statutes the provisions of this chapter "
            "shall be observed,"
        )
        assert "repugnant to some other part of the statute." in section.text
        assert "History of Section." not in section.text
        assert "G.L. 1896, ch. 26, § 1" in section.amendment_notes
        assert "G.L. 1956, § 43-3-2." in section.amendment_notes
        assert section.status.value == "unknown"
        assert section.source_url == SEC43_3_2_URL
        assert section.retrieved_at is not None

    def test_repealed_section(self) -> None:
        ref = _make_ref("43-3-7")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "R.I. Gen. Laws § 43-3-7"
        assert section.heading == "Repealed."
        assert section.text == ""
        assert section.status == StatuteStatus.REPEALED
        assert "Repealed by P.L. 1996, ch. 287, § 1" in section.amendment_notes
        assert section.source_url == SEC43_3_7_URL

    def test_decimal_extension_section(self) -> None:
        ref = _make_ref("43-3-3.1")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "R.I. Gen. Laws § 43-3-3.1"
        assert section.heading == "Gender of titles."
        assert section.text.startswith("Whenever a title which denotes gender")
        assert section.status.value == "unknown"
        assert section.source_url == SEC43_3_3_1_URL

    def test_repealed_range_section(self) -> None:
        title_ref = TitleRef(state_code="RI", identifier="40.1")
        chapter_ref = ChapterRef(title=title_ref, identifier="40.1-1")
        ref = SectionRef(chapter=chapter_ref, identifier="40.1-1-1")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "R.I. Gen. Laws § 40.1-1-1"
        assert section.heading == "[Repealed.]"
        assert section.text == ""
        assert section.status == StatuteStatus.REPEALED
        assert section.source_url == SEC40_1_1_1_URL

    def test_title_mismatch_raises_ref_mismatch_error(self) -> None:
        # Request title 1 but the section page belongs to title 43.
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="RI", identifier="1"),
                identifier="43-3",
            ),
            identifier="43-3-2",
        )
        url = "http://webserver.rilegislature.gov/Statutes/TITLE1/43-3/43-3-2.htm"
        with mock_urlopen_serving({url: REAL_SEC43_3_2_HTML}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(foreign_ref)

    def test_section_mismatch_raises_ref_mismatch_error(self) -> None:
        # Request 43-3-3 but the page's citation is 43-3-2.
        foreign_ref = _make_ref("43-3-3")
        url = "http://webserver.rilegislature.gov/Statutes/TITLE43/43-3/43-3-3.htm"
        with mock_urlopen_serving({url: REAL_SEC43_3_2_HTML}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(foreign_ref)

    def test_missing_section_404_raises_ref_not_found(self) -> None:
        ref = _make_ref("43-3-99")
        url = "http://webserver.rilegislature.gov/Statutes/TITLE43/43-3/43-3-99.htm"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable_error(self) -> None:
        ref = _make_ref("43-3-2")
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestParseEdgeCases:
    def setup_method(self) -> None:
        self.adapter = RhodeIslandAdapter()

    def test_empty_body_raises_normalization_error(self) -> None:
        ref = _make_ref("43-3-2")
        html = (
            "<html><body>"
            "<h1><center>Title 43<br>Statutes and Statutory Construction</center></h1>"
            "<h2><center>Chapter 3<br>Construction and Effect of Statutes</center></h2>"
            "<h3>R.I. Gen. Laws § 43-3-2</h3>"
            '<p style="margin-left:0px"><b>§&nbsp;43-3-2.&nbsp;Empty.</b></p>'
            '<p style="margin-left:0px">   \n   </p>'
            "</body></html>"
        )
        with mock_urlopen_serving({SEC43_3_2_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)

    def test_missing_heading_raises_normalization_error(self) -> None:
        ref = _make_ref("43-3-2")
        html = (
            "<html><body>"
            "<h1><center>Title 43<br>Statutes and Statutory Construction</center></h1>"
            "<h2><center>Chapter 3<br>Construction and Effect of Statutes</center></h2>"
            "<h3>R.I. Gen. Laws § 43-3-2</h3>"
            '<p style="margin-left:0px">   body   </p>'
            "</body></html>"
        )
        with mock_urlopen_serving({SEC43_3_2_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)

    def test_missing_title_anchor_raises_normalization_error(self) -> None:
        ref = _make_ref("43-3-2")
        html = (
            "<html><body>"
            "<h2><center>Chapter 3<br>Construction and Effect of Statutes</center></h2>"
            "<h3>R.I. Gen. Laws § 43-3-2</h3>"
            '<p style="margin-left:0px"><b>§&nbsp;43-3-2.&nbsp;Heading.</b></p>'
            '<p style="margin-left:0px">body</p>'
            "</body></html>"
        )
        with mock_urlopen_serving({SEC43_3_2_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = RhodeIslandAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("43-3-2")
        parsed = ParsedDocument(
            raw_citation="R.I. Gen. Laws § 43-3-2",
            heading="Application of rules of construction.",
            text="In the construction of statutes ...",
            amendment_notes="G.L. 1896, ch. 26, § 1; G.L. 1956, § 43-3-2.",
            source_url=SEC43_3_2_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "R.I. Gen. Laws § 43-3-2"
        assert section.citation.state_code == "RI"
        assert section.heading == "Application of rules of construction."
        assert section.text == "In the construction of statutes ..."
        assert section.amendment_notes == "G.L. 1896, ch. 26, § 1; G.L. 1956, § 43-3-2."
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
            raw_citation="R.I. Gen. Laws § 43-3-2",
            text="Some text.",
        )
        with pytest.raises(NormalizationError):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("43-3-2")
        parsed = ParsedDocument(
            raw_citation="R.I. Gen. Laws § 43-3-3",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError):
            self.adapter.normalize(parsed, ref)

    def test_repealed_heading_sets_status(self) -> None:
        ref = _make_ref("43-3-7")
        parsed = ParsedDocument(
            raw_citation="R.I. Gen. Laws § 43-3-7",
            heading="Repealed.",
            text="",
            amendment_notes="G.L. 1956, § 43-3-7.",
            source_url=SEC43_3_7_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.status == StatuteStatus.REPEALED
        assert section.text == ""

    def test_bracketed_repealed_heading_sets_status(self) -> None:
        title_ref = TitleRef(state_code="RI", identifier="40.1")
        chapter_ref = ChapterRef(title=title_ref, identifier="40.1-1")
        ref = SectionRef(chapter=chapter_ref, identifier="40.1-1-1")
        parsed = ParsedDocument(
            raw_citation="R.I. Gen. Laws § 40.1-1-1",
            heading="[Repealed.]",
            text="",
            source_url=SEC40_1_1_1_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.status == StatuteStatus.REPEALED
        assert section.text == ""
