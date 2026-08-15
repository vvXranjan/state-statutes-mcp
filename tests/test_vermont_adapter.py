"""Tests for VermontAdapter.

Vermont is a server-rendered HTML source (the official Vermont General
Assembly publication of the Vermont Statutes Annotated at
legislature.vermont.gov). Three structural levels (Title -> Chapter ->
Section) map 1:1 onto the framework model; identifiers are the
zero-padded URL segments themselves (``"01"`` for Title 1, ``"017"`` for
Chapter 21/017, ``"01344"`` for § 1344, ``"01301a"`` for the lettered
§ 1301a).

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against **REAL captured Vermont HTML**: verbatim slices
of the official legislature.vermont.gov pages, captured via the Wayback
Machine on Aug 14-15, 2026 and stored under ``tests/fixtures/vermont_*``:

* ``vermont_titles.html`` -- the statutes index page (all 46 title links).
* ``vermont_title01.html`` -- the Title 1 page (13 chapter links).
* ``vermont_chapter21017.html`` -- the Title 21 / Chapter 17 page (123
  section links across 4 ``statutes-list`` blocks).
* ``vermont_section01344.html`` -- section 21 V.S.A. § 1344
  "Disqualifications", including the trailing ``(Amended ...)`` history.

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

from state_statutes_mcp.adapters.vermont.adapter import VermontAdapter
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

# --- REAL fixtures: verbatim slices of the official legislature.vermont.gov
# --- pages captured via the Wayback Machine on Aug 14-15, 2026. NOT synthetic.
FIXTURES = Path(__file__).parent / "fixtures"

REAL_INDEX_HTML = (FIXTURES / "vermont_titles.html").read_text(encoding="utf-8")
REAL_TITLE01_HTML = (FIXTURES / "vermont_title01.html").read_text(encoding="utf-8")
REAL_CH21017_HTML = (FIXTURES / "vermont_chapter21017.html").read_text(
    encoding="utf-8"
)
REAL_SEC01344_HTML = (FIXTURES / "vermont_section01344.html").read_text(
    encoding="utf-8"
)

BASE = "https://legislature.vermont.gov"

INDEX_URL = f"{BASE}/statutes/"
TITLE01_URL = f"{BASE}/statutes/title/01"
CH21017_URL = f"{BASE}/statutes/chapter/21/017"
SEC01344_URL = f"{BASE}/statutes/section/21/017/01344"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _title01_ref() -> TitleRef:
    return TitleRef(state_code="VT", identifier="01")


def _chapter_21017_ref() -> ChapterRef:
    return ChapterRef(title=TitleRef(state_code="VT", identifier="21"), identifier="017")


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_21017_ref(), identifier=section)


def _serve_all() -> dict[str, str]:
    return {
        INDEX_URL: REAL_INDEX_HTML,
        TITLE01_URL: REAL_TITLE01_HTML,
        CH21017_URL: REAL_CH21017_HTML,
        SEC01344_URL: REAL_SEC01344_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert VermontAdapter.__abstractmethods__ == frozenset()
        adapter = VermontAdapter()
        assert adapter.state_code == "VT"
        assert adapter.state_name == "Vermont"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = VermontAdapter()

    def test_title_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_title01_ref())
            == "https://legislature.vermont.gov/statutes/title/01"
        )

    def test_chapter_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_chapter_21017_ref())
            == "https://legislature.vermont.gov/statutes/chapter/21/017"
        )

    def test_section_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("01344"))
            == "https://legislature.vermont.gov/statutes/section/21/017/01344"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestDiscovery:
    def setup_method(self) -> None:
        self.adapter = VermontAdapter()

    def test_list_titles_real_fixture(self) -> None:
        with mock_urlopen_serving({INDEX_URL: REAL_INDEX_HTML}):
            titles = self.adapter.list_titles()

        identifiers = [n.identifier for n in titles]
        assert len(identifiers) == 46
        assert identifiers[0] == "01"
        assert identifiers[-1] == "33"
        assert "21" in identifiers
        assert "09A" in identifiers
        assert "03APPENDIX" in identifiers
        assert all(n.level == HierarchyLevel.TITLE for n in titles)
        assert all(n.ref.state_code == "VT" for n in titles)

    def test_list_titles_names(self) -> None:
        with mock_urlopen_serving({INDEX_URL: REAL_INDEX_HTML}):
            titles = self.adapter.list_titles()
        by_id = {n.identifier: n.name for n in titles}
        assert by_id["01"] == "General Provisions"
        assert by_id["21"] == "Labor"
        assert by_id["09A"] == "Uniform Commercial Code"
        assert by_id["03APPENDIX"] == "Executive Orders"

    def test_list_titles_sorted_numerically(self) -> None:
        with mock_urlopen_serving({INDEX_URL: REAL_INDEX_HTML}):
            titles = self.adapter.list_titles()
        # 03APPENDIX (numeric prefix 3) sorts right after 03, before 04.
        ids = [n.identifier for n in titles]
        assert ids.index("03APPENDIX") == ids.index("03") + 1
        assert ids.index("03") < ids.index("04")

    def test_list_titles_no_links_raises(self) -> None:
        with mock_urlopen("<html><body>no titles here</body></html>"):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_titles_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_chapters_real_fixture(self) -> None:
        with mock_urlopen_serving({TITLE01_URL: REAL_TITLE01_HTML}):
            chapters = self.adapter.list_chapters(_title01_ref())

        assert len(chapters) == 13
        assert [n.identifier for n in chapters][:3] == ["001", "003", "005"]
        assert [n.name for n in chapters][:3] == [
            "Vermont Statutes Annotated",
            "Construction of Statutes",
            "Common Law; General Rights",
        ]
        assert [n.identifier for n in chapters][-1] == "025"
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)
        assert all(n.ref.title == _title01_ref() for n in chapters)

    def test_list_chapters_unknown_title_raises_ref_not_found(self) -> None:
        title_ref = TitleRef(state_code="VT", identifier="99")
        url = f"{BASE}/statutes/title/99"
        with mock_urlopen_serving({url: REAL_TITLE01_HTML}):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_chapters(title_ref)

    def test_list_chapters_404_raises_ref_not_found(self) -> None:
        title_ref = TitleRef(state_code="VT", identifier="99")
        url = f"{BASE}/statutes/title/99"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_chapters(title_ref)

    def test_list_chapters_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(_title01_ref())

    def test_list_sections_real_fixture(self) -> None:
        with mock_urlopen_serving({CH21017_URL: REAL_CH21017_HTML}):
            sections = self.adapter.list_sections(_chapter_21017_ref())

        assert len(sections) == 123
        assert [n.identifier for n in sections][:3] == ["01301", "01301a", "01301b"]
        assert [n.name for n in sections][:3] == [
            "Definitions",
            "Department of Labor; composition",
            "Repealed. 2001, No. 142, § 302c.",
        ]
        assert [n.identifier for n in sections][-1] == "01471"
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == _chapter_21017_ref() for n in sections)

    def test_list_sections_lettered_and_repealed_names(self) -> None:
        with mock_urlopen_serving({CH21017_URL: REAL_CH21017_HTML}):
            sections = self.adapter.list_sections(_chapter_21017_ref())
        by_id = {n.identifier: n.name for n in sections}
        assert by_id["01301a"] == "Department of Labor; composition"
        assert by_id["01301b"] == "Repealed. 2001, No. 142, § 302c."
        assert by_id["01423b"] == (
            "Repealed. 2009, No. 156 (Adj. Sess.), § E.401.4, eff. June 3, 2010."
        )

    def test_list_sections_sorted_numerically(self) -> None:
        with mock_urlopen_serving({CH21017_URL: REAL_CH21017_HTML}):
            sections = self.adapter.list_sections(_chapter_21017_ref())
        ids = [n.identifier for n in sections]
        # Lettered 01301a/01301b sort right after 01301, before 01302.
        assert ids.index("01301") < ids.index("01301a") < ids.index("01301b")
        assert ids.index("01301b") < ids.index("01302")

    def test_list_sections_unknown_chapter_raises_ref_not_found(self) -> None:
        chapter_ref = ChapterRef(
            title=TitleRef(state_code="VT", identifier="21"), identifier="999"
        )
        url = f"{BASE}/statutes/chapter/21/999"
        with mock_urlopen_serving({url: REAL_CH21017_HTML}):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_sections(chapter_ref)

    def test_list_sections_404_raises_ref_not_found(self) -> None:
        chapter_ref = ChapterRef(
            title=TitleRef(state_code="VT", identifier="21"), identifier="999"
        )
        url = f"{BASE}/statutes/chapter/21/999"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_sections(chapter_ref)


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = VermontAdapter()

    def test_section_full_retrieval(self) -> None:
        ref = _make_ref("01344")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "21 V.S.A. § 1344"
        assert section.citation.state_code == "VT"
        assert section.ref == ref
        assert section.heading == "Disqualifications"
        assert section.text.startswith("(a) An individual shall be disqualified for benefits:")
        assert "§ 1344. Disqualifications" not in section.text
        assert "(Amended" not in section.text
        assert "(a) An individual" in section.text
        assert section.status.value == "unknown"
        assert section.amendment_notes is not None
        assert section.amendment_notes.startswith("(Amended 1959, No. 236;")
        assert "2023, No. 6, § 252, eff. July 1, 2023.)" in section.amendment_notes
        assert section.source_url == SEC01344_URL
        assert section.retrieved_at is not None

    def test_title_mismatch_raises_ref_mismatch_error(self) -> None:
        # Request title 01 but the section page belongs to title 21.
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="VT", identifier="01"),
                identifier="017",
            ),
            identifier="01344",
        )
        url = f"{BASE}/statutes/section/01/017/01344"
        with mock_urlopen_serving({url: REAL_SEC01344_HTML}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(foreign_ref)

    def test_chapter_mismatch_raises_ref_mismatch_error(self) -> None:
        # Request chapter 001 but the section page belongs to chapter 017.
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="VT", identifier="21"),
                identifier="001",
            ),
            identifier="01344",
        )
        url = f"{BASE}/statutes/section/21/001/01344"
        with mock_urlopen_serving({url: REAL_SEC01344_HTML}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(foreign_ref)

    def test_missing_section_404_raises_ref_not_found(self) -> None:
        ref = _make_ref("99999")
        url = f"{BASE}/statutes/section/21/017/99999"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable_error(self) -> None:
        ref = _make_ref("01344")
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestParseEdgeCases:
    def setup_method(self) -> None:
        self.adapter = VermontAdapter()

    def test_missing_heading_raises_normalization_error(self) -> None:
        ref = _make_ref("01344")
        html = (
            "<h2 class=\"statute-title\"><a href=\"/statutes/title/21\">Title 21</a></h2>"
            "<h3 class=\"statute-chapter\"><a href=\"/statutes/chapter/21/017\">Chapter 017</a></h3>"
            "<b>(Cite as: 21 V.S.A. § 1344)</b>"
            '<ul class="item-list statutes-detail"><li><p></p><p style="margin-left:0px">no bold heading here</p></li></ul>'
        )
        with mock_urlopen_serving({SEC01344_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)

    def test_empty_body_raises_normalization_error(self) -> None:
        ref = _make_ref("01344")
        html = (
            "<h2 class=\"statute-title\"><a href=\"/statutes/title/21\">Title 21</a></h2>"
            "<h3 class=\"statute-chapter\"><a href=\"/statutes/chapter/21/017\">Chapter 017</a></h3>"
            "<b>(Cite as: 21 V.S.A. § 1344)</b>"
            '<ul class="item-list statutes-detail"><li><p></p><p style="margin-left:0px"><b>§ 1344. X</b></p></li></ul>'
        )
        with mock_urlopen_serving({SEC01344_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)

    def test_missing_title_anchor_raises_normalization_error(self) -> None:
        ref = _make_ref("01344")
        html = (
            "<h3 class=\"statute-chapter\"><a href=\"/statutes/chapter/21/017\">Chapter 017</a></h3>"
            "<b>(Cite as: 21 V.S.A. § 1344)</b>"
            '<ul class="item-list statutes-detail"><li><p></p><p style="margin-left:0px"><b>§ 1344. X</b></p><p>(a) body</p></li></ul>'
        )
        with mock_urlopen_serving({SEC01344_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = VermontAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("01344")
        parsed = ParsedDocument(
            raw_citation="21 V.S.A. § 1344",
            heading="Disqualifications",
            text="(a) An individual shall be disqualified for benefits:",
            amendment_notes="(Amended 1959, No. 236; ... 2023, No. 6, § 252.)",
            source_url=SEC01344_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "21 V.S.A. § 1344"
        assert section.citation.state_code == "VT"
        assert section.heading == "Disqualifications"
        assert section.text == "(a) An individual shall be disqualified for benefits:"
        assert section.amendment_notes == "(Amended 1959, No. 236; ... 2023, No. 6, § 252.)"
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
            raw_citation="21 V.S.A. § 1344",
            text="Some text.",
        )
        with pytest.raises(NormalizationError):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("01344")
        parsed = ParsedDocument(
            raw_citation="21 V.S.A. § 1301",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError):
            self.adapter.normalize(parsed, ref)
