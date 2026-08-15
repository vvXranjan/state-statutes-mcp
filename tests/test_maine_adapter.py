"""Tests for MaineAdapter.

Maine is a server-rendered HTML source (the official Maine Legislature
publication of the Maine Revised Statutes at legislature.maine.gov). Three
structural levels (Title -> Chapter -> Section) map 1:1 onto the framework
model; section identifiers may carry a letter suffix (``4-A``, ``19-A``)
or a numeric dash suffix (``18-1``).

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against **REAL captured Maine HTML**: verbatim slices
of the official legislature.maine.gov/statutes pages, captured live on
Aug 15, 2026 and stored under ``tests/fixtures/maine_*``:

* ``maine_homepage_titles.html`` -- the statutes homepage title list
  (all 64 titles, including lettered titles).
* ``maine_title17a_contents.html`` -- the Title 17-A contents page
  (52 chapters, including lettered ``54-A`` ... ``54-G``).
* ``maine_title17a_ch1.html`` -- the Chapter 1 TOC page (26 sections,
  including lettered ``4-A`` and dashed ``18-1``).
* ``maine_title17a_sec2.html`` -- section 2 "Definitions".
* ``maine_title17a_sec5.html`` -- section 5, a repealed section.
* ``maine_title17a_sec18_1.html`` -- section 18-1, the dashed-identifier
  edge case (its URL file suffix is ``18-1``; its listing label reads
  ``17-A §18.``).

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

from state_statutes_mcp.adapters.maine.adapter import MaineAdapter
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

# --- REAL fixtures: verbatim slices of the official Maine Legislature
# --- statutes pages captured live on Aug 15, 2026. NOT synthetic.
FIXTURES = Path(__file__).parent / "fixtures"

REAL_HOMEPAGE_HTML = (FIXTURES / "maine_homepage_titles.html").read_text(
    encoding="utf-8"
)
REAL_TITLE17A_CONTENTS_HTML = (
    FIXTURES / "maine_title17a_contents.html"
).read_text(encoding="utf-8")
REAL_CH1_HTML = (FIXTURES / "maine_title17a_ch1.html").read_text(encoding="utf-8")
REAL_SEC2_HTML = (FIXTURES / "maine_title17a_sec2.html").read_text(encoding="utf-8")
REAL_SEC5_HTML = (FIXTURES / "maine_title17a_sec5.html").read_text(encoding="utf-8")
REAL_SEC18_1_HTML = (FIXTURES / "maine_title17a_sec18_1.html").read_text(
    encoding="utf-8"
)

BASE = "https://legislature.maine.gov/statutes"

HOMEPAGE_URL = f"{BASE}/homepage.html"
TITLE17A_URL = f"{BASE}/17-A/title17-Ach0sec0.html"
CH1_URL = f"{BASE}/17-A/title17-Ach1sec0.html"
SEC2_URL = f"{BASE}/17-A/title17-Asec2.html"
SEC5_URL = f"{BASE}/17-A/title17-Asec5.html"
SEC18_1_URL = f"{BASE}/17-A/title17-Asec18-1.html"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _title_ref() -> TitleRef:
    return TitleRef(state_code="ME", identifier="17-A")


def _chapter_ref() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="1")


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


def _serve_all() -> dict[str, str]:
    return {
        HOMEPAGE_URL: REAL_HOMEPAGE_HTML,
        TITLE17A_URL: REAL_TITLE17A_CONTENTS_HTML,
        CH1_URL: REAL_CH1_HTML,
        SEC2_URL: REAL_SEC2_HTML,
        SEC5_URL: REAL_SEC5_HTML,
        SEC18_1_URL: REAL_SEC18_1_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert MaineAdapter.__abstractmethods__ == frozenset()
        adapter = MaineAdapter()
        assert adapter.state_code == "ME"
        assert adapter.state_name == "Maine"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = MaineAdapter()

    def test_title_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_title_ref())
            == "https://legislature.maine.gov/statutes/17-A/title17-Ach0sec0.html"
        )

    def test_chapter_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_chapter_ref())
            == "https://legislature.maine.gov/statutes/17-A/title17-Ach1sec0.html"
        )

    def test_section_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("2"))
            == "https://legislature.maine.gov/statutes/17-A/title17-Asec2.html"
        )

    def test_section_ref_url_lettered(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("4-A"))
            == "https://legislature.maine.gov/statutes/17-A/title17-Asec4-A.html"
        )

    def test_section_ref_url_dashed_edge_case(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("18-1"))
            == "https://legislature.maine.gov/statutes/17-A/title17-Asec18-1.html"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestDiscovery:
    def setup_method(self) -> None:
        self.adapter = MaineAdapter()

    def test_list_titles_real_fixture(self) -> None:
        with mock_urlopen_serving({HOMEPAGE_URL: REAL_HOMEPAGE_HTML}):
            titles = self.adapter.list_titles()

        identifiers = [n.identifier for n in titles]
        assert len(identifiers) == 64
        assert identifiers[:5] == ["1", "2", "3", "4", "5"]
        assert titles[0].name == "GENERAL PROVISIONS"
        assert all(n.level == HierarchyLevel.TITLE for n in titles)
        assert all(n.ref.state_code == "ME" for n in titles)
        assert "17-A" in identifiers and "39-A" in identifiers

    def test_list_titles_numeric_order(self) -> None:
        with mock_urlopen_serving({HOMEPAGE_URL: REAL_HOMEPAGE_HTML}):
            titles = self.adapter.list_titles()
        identifiers = [n.identifier for n in titles]
        # Lettered titles sort with their leading number: 1, 2, ..., 7, 7-A, 8 ...
        assert identifiers == sorted(identifiers, key=lambda s: (int(s.split("-")[0]), s))

    def test_list_titles_lettered_title_name(self) -> None:
        with mock_urlopen_serving({HOMEPAGE_URL: REAL_HOMEPAGE_HTML}):
            titles = self.adapter.list_titles()
        by_id = {n.identifier: n.name for n in titles}
        assert by_id["17-A"] == "MAINE CRIMINAL CODE"
        assert by_id["1"] == "GENERAL PROVISIONS"

    def test_list_titles_no_title_links_raises(self) -> None:
        with mock_urlopen("<html><body>no titles here</body></html>"):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_titles_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_chapters_real_fixture(self) -> None:
        with mock_urlopen_serving({TITLE17A_URL: REAL_TITLE17A_CONTENTS_HTML}):
            chapters = self.adapter.list_chapters(_title_ref())

        assert len(chapters) == 52
        assert [n.identifier for n in chapters][:3] == ["1", "2", "3"]
        assert [n.name for n in chapters][:3] == [
            "PRELIMINARY",
            "CRIMINAL LIABILITY; ELEMENTS OF CRIMES",
            "CRIMINAL LIABILITY OF ACCOMPLICES, ORGANIZATIONS AND PLANTS",
        ]
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)
        assert all(n.ref.title == _title_ref() for n in chapters)
        assert "54-A" in [n.identifier for n in chapters]

    def test_list_chapters_lettered_name(self) -> None:
        with mock_urlopen_serving({TITLE17A_URL: REAL_TITLE17A_CONTENTS_HTML}):
            chapters = self.adapter.list_chapters(_title_ref())
        by_id = {n.identifier: n.name for n in chapters}
        assert by_id["54-A"] == "PROTECTIVE ORDER"

    def test_list_chapters_404_raises_ref_not_found(self) -> None:
        title_ref = TitleRef(state_code="ME", identifier="999")
        url = "https://legislature.maine.gov/statutes/999/title999ch0sec0.html"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_chapters(title_ref)

    def test_list_chapters_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(_title_ref())

    def test_list_sections_real_fixture(self) -> None:
        with mock_urlopen_serving({CH1_URL: REAL_CH1_HTML}):
            sections = self.adapter.list_sections(_chapter_ref())

        assert len(sections) == 26
        assert [n.identifier for n in sections][:3] == ["1", "2", "3"]
        assert [n.name for n in sections][:3] == [
            "Title; effective date; severability",
            "Definitions",
            "All crimes defined by statute; civil actions",
        ]
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == _chapter_ref() for n in sections)

    def test_list_sections_lettered_and_dashed_identifiers(self) -> None:
        with mock_urlopen_serving({CH1_URL: REAL_CH1_HTML}):
            sections = self.adapter.list_sections(_chapter_ref())
        by_id = {n.identifier: n.name for n in sections}
        assert by_id["4-A"] == "Crimes and civil violations outside the code"
        assert by_id["18-1"] == "Homelessness crisis protocol"
        assert by_id["19-A"] == (
            "Election to charge Class E crime as civil violation "
            "(WHOLE SECTION TEXT EFFECTIVE 1/01/26)"
        )

    def test_list_sections_repealed_marker_preserved(self) -> None:
        with mock_urlopen_serving({CH1_URL: REAL_CH1_HTML}):
            sections = self.adapter.list_sections(_chapter_ref())
        by_id = {n.identifier: n.name for n in sections}
        assert by_id["5"] == "Pleading and proof (REPEALED)"

    def test_list_sections_404_raises_ref_not_found(self) -> None:
        chapter_ref = ChapterRef(title=_title_ref(), identifier="999")
        url = "https://legislature.maine.gov/statutes/17-A/title17-Ach999sec0.html"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_sections(chapter_ref)

    def test_list_sections_no_links_raises(self) -> None:
        with mock_urlopen_serving({CH1_URL: "<html><body>no sections</body></html>"}):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_sections(_chapter_ref())


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = MaineAdapter()

    def test_simple_section_full_retrieval(self) -> None:
        ref = _make_ref("2")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "17-A M.R.S. § 2"
        assert section.citation.state_code == "ME"
        assert section.ref == ref
        assert section.heading == "Definitions"
        assert section.text.startswith(
            "As used in this code, unless a different meaning is plainly "
            "required, the following words"
        )
        assert '"Act" or "action" means a voluntary bodily movement.' in section.text
        assert '"Year," for purposes of imposing imprisonment or probation' in section.text
        assert "PL 1975, c. 499, §1 (NEW)." in section.amendment_notes
        assert "PL 1995, c." in section.amendment_notes
        assert section.status.value == "unknown"
        assert section.source_url == SEC2_URL
        assert section.retrieved_at is not None

    def test_repealed_section(self) -> None:
        ref = _make_ref("5")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "17-A M.R.S. § 5"
        assert section.heading == "Pleading and proof"
        assert section.text == "(REPEALED)"
        assert section.status.value == "unknown"
        assert "PL 1981, c. 324, §8 (RP)." in section.amendment_notes

    def test_dashed_identifier_section(self) -> None:
        ref = _make_ref("18-1")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "17-A M.R.S. § 18-1"
        assert section.heading == "Homelessness crisis protocol"
        assert section.text.startswith("A person who lacks a home")
        assert section.status.value == "unknown"

    def test_revisors_note_appended_to_amendment_notes(self) -> None:
        ref = _make_ref("18-1")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert "PL 2021, c. 393, §1 (NEW)." in section.amendment_notes
        assert "Revisor's Note:" in section.amendment_notes
        assert "REALLOCATED TO TITLE 17-A, SECTION 19" in section.amendment_notes
        assert "Revisor's Note" not in section.text

    def test_title_mismatch_raises_ref_mismatch_error(self) -> None:
        # Request title 1 but the section page belongs to title 17-A.
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="ME", identifier="1"),
                identifier="1",
            ),
            identifier="2",
        )
        url = "https://legislature.maine.gov/statutes/1/title1sec2.html"
        with mock_urlopen_serving({url: REAL_SEC2_HTML}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(foreign_ref)

    def test_chapter_mismatch_raises_ref_mismatch_error(self) -> None:
        # Request chapter 2 but the section page belongs to chapter 1.
        foreign_ref = SectionRef(
            chapter=ChapterRef(title=_title_ref(), identifier="2"),
            identifier="2",
        )
        with mock_urlopen_serving({SEC2_URL: REAL_SEC2_HTML}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(foreign_ref)

    def test_missing_section_404_raises_ref_not_found(self) -> None:
        ref = _make_ref("9999")
        url = "https://legislature.maine.gov/statutes/17-A/title17-Asec9999.html"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable_error(self) -> None:
        ref = _make_ref("2")
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestParseEdgeCases:
    def setup_method(self) -> None:
        self.adapter = MaineAdapter()

    def test_empty_body_raises_normalization_error(self) -> None:
        ref = _make_ref("2")
        html = (
            '<div class="MRSTitle toc">Title 17-A: MAINE CRIMINAL CODE</div>'
            '<div class="MRSChapter toc">Chapter 1: PRELIMINARY</div>'
            '<h3 class="heading_section">\n §2. Empty</h3>'
            '<div class="mrs-text indpara MRSIndentedPara status_current IP">   \n </div>'
            '<div class="qhistory">SECTION HISTORY'
            '<div class="qhistory_list"><span class="hist_chapter">PL 1975, c. 499, '
            "§1 (NEW).</span></div></div>"
        )
        with mock_urlopen_serving({SEC2_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)

    def test_missing_heading_raises_normalization_error(self) -> None:
        ref = _make_ref("2")
        html = (
            '<div class="MRSTitle toc">Title 17-A: MAINE CRIMINAL CODE</div>'
            '<div class="MRSChapter toc">Chapter 1: PRELIMINARY</div>'
            '<div class="mrs-text indpara MRSIndentedPara status_current IP">body</div>'
            '<div class="qhistory">SECTION HISTORY</div>'
        )
        with mock_urlopen_serving({SEC2_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)

    def test_missing_title_toc_raises_normalization_error(self) -> None:
        ref = _make_ref("2")
        html = (
            '<div class="MRSChapter toc">Chapter 1: PRELIMINARY</div>'
            '<h3 class="heading_section">\n §2. Definitions</h3>'
            '<div class="mrs-text indpara MRSIndentedPara status_current IP">body</div>'
        )
        with mock_urlopen_serving({SEC2_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = MaineAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("2")
        parsed = ParsedDocument(
            raw_citation="17-A M.R.S. § 2",
            heading="Definitions",
            text="As used in this code ...",
            amendment_notes="PL 1975, c. 499, §1 (NEW).",
            source_url=SEC2_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "17-A M.R.S. § 2"
        assert section.citation.state_code == "ME"
        assert section.heading == "Definitions"
        assert section.text == "As used in this code ..."
        assert section.amendment_notes == "PL 1975, c. 499, §1 (NEW)."
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
            raw_citation="17-A M.R.S. § 2",
            text="Some text.",
        )
        with pytest.raises(NormalizationError):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("2")
        parsed = ParsedDocument(
            raw_citation="17-A M.R.S. § 3",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError):
            self.adapter.normalize(parsed, ref)
