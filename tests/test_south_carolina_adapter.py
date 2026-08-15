"""Tests for SouthCarolinaAdapter.

South Carolina is a server-rendered HTML source (the official South
Carolina Legislature publication of the Code of Laws of South Carolina at
scstatehouse.gov). Three structural levels (Title -> Chapter -> Section)
map cleanly onto the framework model:

* ``TitleRef.identifier`` is the title number (e.g. ``"1"``);
  ``TitleRef.name`` is the title heading (e.g. ``"Administration of the
  Government"``).
* ``ChapterRef.identifier`` is the chapter number (e.g. ``"1"``); the
  chapter page URL zero-pads the title to 2 digits and the chapter to 3
  digits (``t01c001.php``).
* ``SectionRef.identifier`` is the full ``{t}-{c}-{s}`` citation (e.g.
  ``"1-1-10"``).

Sections are embedded in their chapter page, so both section listing and
section retrieval read from ``/code/t{NN}c{NNN}.php`` (the same pattern
Delaware and Florida use for chapter-document sources).

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against **REAL captured South Carolina HTML**: verbatim
slices of the official scstatehouse.gov pages, captured live on Aug 15,
2026 and stored under ``tests/fixtures/sc_*``:

* ``sc_statmast.php`` -- the master title page (all 63 titles).
* ``sc_title1.php`` -- the Title 1 page (21 chapters).
* ``sc_t01c001.php`` -- chapter 1-1 "General Provisions" (85 sections,
  including lettered sections like ``1-1-714A`` and ``HISTORY:`` lines).
* ``sc_t01c003.php`` -- chapter 1-3 (32 sections, each with a ``HISTORY:``
  line).

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

from state_statutes_mcp.adapters.south_carolina.adapter import SouthCarolinaAdapter
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

# --- REAL fixtures: verbatim slices of the official South Carolina
# --- Legislature pages captured live on Aug 15, 2026. NOT synthetic.
FIXTURES = Path(__file__).parent / "fixtures"

REAL_STATMAST_HTML = (FIXTURES / "sc_statmast.php").read_text(encoding="latin-1")
REAL_TITLE1_HTML = (FIXTURES / "sc_title1.php").read_text(encoding="latin-1")
REAL_T01C001_HTML = (FIXTURES / "sc_t01c001.php").read_text(encoding="latin-1")
REAL_T01C003_HTML = (FIXTURES / "sc_t01c003.php").read_text(encoding="latin-1")

BASE = "https://www.scstatehouse.gov"

STATMAST_URL = f"{BASE}/code/statmast.php"
TITLE1_URL = f"{BASE}/code/title1.php"
T01C001_URL = f"{BASE}/code/t01c001.php"
T01C003_URL = f"{BASE}/code/t01c003.php"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _title_ref() -> TitleRef:
    return TitleRef(state_code="SC", identifier="1")


def _chapter_ref() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="1")


def _chapter_3_ref() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="3")


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


def _serve_all() -> dict[str, str]:
    return {
        STATMAST_URL: REAL_STATMAST_HTML,
        TITLE1_URL: REAL_TITLE1_HTML,
        T01C001_URL: REAL_T01C001_HTML,
        T01C003_URL: REAL_T01C003_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert SouthCarolinaAdapter.__abstractmethods__ == frozenset()
        adapter = SouthCarolinaAdapter()
        assert adapter.state_code == "SC"
        assert adapter.state_name == "South Carolina"


class TestChapterUrl:
    def test_single_digit_title_and_chapter(self) -> None:
        assert SouthCarolinaAdapter._chapter_url("1", "1") == "/code/t01c001.php"

    def test_two_digit_title(self) -> None:
        assert SouthCarolinaAdapter._chapter_url("63", "1") == "/code/t63c001.php"

    def test_three_digit_chapter(self) -> None:
        assert SouthCarolinaAdapter._chapter_url("1", "110") == "/code/t01c110.php"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = SouthCarolinaAdapter()

    def test_title_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_title_ref())
            == "https://www.scstatehouse.gov/code/title1.php"
        )

    def test_chapter_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_chapter_ref())
            == "https://www.scstatehouse.gov/code/t01c001.php"
        )

    def test_section_ref_url_is_chapter_page(self) -> None:
        # Sections are embedded in their chapter page.
        assert (
            self.adapter.build_url(_make_ref("1-1-10"))
            == "https://www.scstatehouse.gov/code/t01c001.php"
        )

    def test_two_digit_title_chapter_ref_url(self) -> None:
        title = TitleRef(state_code="SC", identifier="63")
        chapter = ChapterRef(title=title, identifier="1")
        assert (
            self.adapter.build_url(chapter)
            == "https://www.scstatehouse.gov/code/t63c001.php"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def test_returns_all_titles(self) -> None:
        adapter = SouthCarolinaAdapter()
        with mock_urlopen_serving({STATMAST_URL: REAL_STATMAST_HTML}):
            titles = adapter.list_titles()

        assert len(titles) == 63
        first = titles[0]
        assert first.level == HierarchyLevel.TITLE
        assert first.identifier == "1"
        assert first.name == "Administration of the Government"
        assert first.ref.state_code == "SC"
        identifiers = [node.identifier for node in titles]
        assert "63" in identifiers
        assert identifiers == [str(i) for i in range(1, 64)]
        assert len(set(identifiers)) == 63

    def test_entity_in_title_name_decoded(self) -> None:
        adapter = SouthCarolinaAdapter()
        with mock_urlopen_serving({STATMAST_URL: REAL_STATMAST_HTML}):
            titles = adapter.list_titles()
        by_id = {node.identifier: node.name for node in titles}
        # Title 63's name is 'South Carolina Children&#39;s Code' in the
        # raw HTML; the apostrophe entity must decode.
        assert by_id["63"] == "South Carolina Children's Code"

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = SouthCarolinaAdapter()
        with mock_urlopen("<html><body>no titles here</body></html>"):
            with pytest.raises(AdapterUnavailableError, match="no usable title"):
                adapter.list_titles()

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = SouthCarolinaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_titles()


class TestListChapters:
    def test_returns_chapters_from_title_page(self) -> None:
        adapter = SouthCarolinaAdapter()
        with mock_urlopen_serving({TITLE1_URL: REAL_TITLE1_HTML}):
            chapters = adapter.list_chapters(_title_ref())

        assert len(chapters) == 21
        first = chapters[0]
        assert first.level == HierarchyLevel.CHAPTER
        assert first.identifier == "1"
        assert first.name == "GENERAL PROVISIONS"
        assert first.ref.title.identifier == "1"
        assert first.ref.state_code == "SC"
        identifiers = [node.identifier for node in chapters]
        assert "3" in identifiers
        assert "34" in identifiers
        assert len(set(identifiers)) == 21

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = SouthCarolinaAdapter()
        with mock_urlopen_error(_http_error(TITLE1_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_chapters(_title_ref())

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = SouthCarolinaAdapter()
        with mock_urlopen("<html><body>no chapters</body></html>"):
            with pytest.raises(AdapterUnavailableError, match="no usable chapter"):
                adapter.list_chapters(_title_ref())


class TestListSections:
    def test_returns_sections_from_chapter_page(self) -> None:
        adapter = SouthCarolinaAdapter()
        with mock_urlopen_serving({T01C001_URL: REAL_T01C001_HTML}):
            sections = adapter.list_sections(_chapter_ref())

        identifiers = [node.identifier for node in sections]
        assert identifiers[0] == "1-1-10"
        assert len(identifiers) == 86
        assert len(set(identifiers)) == 86
        first = sections[0]
        assert first.level == HierarchyLevel.SECTION
        assert first.name == "Jurisdiction and boundaries of the State."
        assert first.ref.chapter.identifier == "1"
        assert first.ref.state_code == "SC"

    def test_lettered_section_appears(self) -> None:
        adapter = SouthCarolinaAdapter()
        with mock_urlopen_serving({T01C001_URL: REAL_T01C001_HTML}):
            sections = adapter.list_sections(_chapter_ref())
        identifiers = [node.identifier for node in sections]
        assert "1-1-714A" in identifiers

    def test_other_chapter_page(self) -> None:
        adapter = SouthCarolinaAdapter()
        with mock_urlopen_serving({T01C003_URL: REAL_T01C003_HTML}):
            sections = adapter.list_sections(_chapter_3_ref())
        identifiers = [node.identifier for node in sections]
        assert identifiers[0] == "1-3-10"
        assert len(identifiers) == 32

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = SouthCarolinaAdapter()
        with mock_urlopen_error(_http_error(T01C001_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_sections(_chapter_ref())

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = SouthCarolinaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_sections(_chapter_ref())


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = SouthCarolinaAdapter()

    def test_happy_path(self) -> None:
        parsed = ParsedDocument(
            raw_citation="S.C. Code § 1-1-10",
            heading="Jurisdiction and boundaries of the State.",
            text="The sovereignty and jurisdiction of this State extends",
            amendment_notes="HISTORY: 1962 Code SECTION 39-1; 1952 Code SECTION 39-1",
            source_url=T01C001_URL,
            retrieved_at=None,
        )
        section = self.adapter.normalize(parsed, _make_ref("1-1-10"))

        assert section.citation.raw == "S.C. Code § 1-1-10"
        assert section.citation.state_code == "SC"
        assert section.heading == "Jurisdiction and boundaries of the State."
        assert section.text.startswith("The sovereignty and jurisdiction")
        assert section.amendment_notes.startswith("HISTORY: 1962 Code")
        assert section.status.value == "unknown"

    def test_wrong_state_raises_normalization_error(self) -> None:
        parsed = ParsedDocument(
            raw_citation="S.C. Code § 1-1-10",
            heading=None,
            text="body",
            amendment_notes=None,
            source_url=None,
            retrieved_at=None,
        )
        other_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="NC", identifier="1"), identifier="1"
            ),
            identifier="1-1-10",
        )
        with pytest.raises(NormalizationError, match="expected 'SC'"):
            self.adapter.normalize(parsed, other_ref)

    def test_ref_mismatch_raises(self) -> None:
        parsed = ParsedDocument(
            raw_citation="S.C. Code § 1-1-20",
            heading=None,
            text="body",
            amendment_notes=None,
            source_url=None,
            retrieved_at=None,
        )
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, _make_ref("1-1-10"))


class TestRetrieveSection:
    def test_simple_section(self) -> None:
        adapter = SouthCarolinaAdapter()
        with mock_urlopen_serving(_serve_all()):
            section = adapter.retrieve_section(_make_ref("1-1-10"))

        assert section.ref.identifier == "1-1-10"
        assert section.citation.raw == "S.C. Code § 1-1-10"
        assert section.heading == "Jurisdiction and boundaries of the State."
        assert section.text.startswith(
            "The sovereignty and jurisdiction of this State extends"
        )
        assert "HISTORY" not in section.text
        assert section.amendment_notes is not None
        assert section.amendment_notes.startswith("HISTORY: 1962 Code")
        assert section.source_url == T01C001_URL
        assert section.status.value == "unknown"
        assert section.retrieved_at is not None

    def test_history_and_article_divider(self) -> None:
        # 1-1-30's HISTORY is followed by an ARTICLE divider; the divider
        # must not leak into the amendment notes.
        adapter = SouthCarolinaAdapter()
        with mock_urlopen_serving(_serve_all()):
            section = adapter.retrieve_section(_make_ref("1-1-30"))

        assert section.heading == "Daylight saving time observation."
        assert section.text.startswith(
            "If the United States Congress amends 15 U.S.C."
        )
        assert section.amendment_notes == (
            "HISTORY: 2020 Act No. 113 (S.11), SECTION 1, eff February 3, 2020."
        )

    def test_lettered_section(self) -> None:
        adapter = SouthCarolinaAdapter()
        with mock_urlopen_serving(_serve_all()):
            section = adapter.retrieve_section(_make_ref("1-1-714A"))

        assert section.citation.raw == "S.C. Code § 1-1-714A"
        assert section.heading == "Official state heritage work animal."
        assert section.text.startswith(
            "The mule is hereby designated as the official State Heritage "
            "Work Animal of South Carolina."
        )
        assert section.amendment_notes.startswith("HISTORY: 2010 Act No. 240")

    def test_other_chapter_page(self) -> None:
        adapter = SouthCarolinaAdapter()
        ref = SectionRef(chapter=_chapter_3_ref(), identifier="1-3-10")
        with mock_urlopen_serving(_serve_all()):
            section = adapter.retrieve_section(ref)

        assert section.ref.identifier == "1-3-10"
        assert section.heading == (
            "Departments, agencies and the like shall furnish information "
            "requested by Governor."
        )
        assert section.text.startswith(
            "The departments, bureaus, divisions, officers, boards, "
            "commissions, institutions and other agencies"
        )
        assert section.amendment_notes.startswith("HISTORY: 1962 Code SECTION 1-101")
        assert section.source_url == T01C003_URL

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = SouthCarolinaAdapter()
        with mock_urlopen_error(_http_error(T01C001_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.retrieve_section(_make_ref("1-1-10"))

    def test_missing_section_on_chapter_page_raises_ref_not_found(self) -> None:
        # 1-1-20 exists on the page; a section number that does not (1-1-21)
        # must raise RefNotFoundError rather than being silently misread.
        adapter = SouthCarolinaAdapter()
        missing = _make_ref("1-1-21")
        with mock_urlopen_serving({T01C001_URL: REAL_T01C001_HTML}):
            with pytest.raises(RefNotFoundError, match="contains no section"):
                adapter.retrieve_section(missing)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = SouthCarolinaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.retrieve_section(_make_ref("1-1-10"))

    def test_empty_body_raises_normalization_error(self) -> None:
        adapter = SouthCarolinaAdapter()
        malformed = (
            '<html><body><span style="font-weight: bold;"> SECTION 1-1-10.</span>'
            " Heading.<br /><br />\n\t<br /><br />\nHISTORY: none.<br /><br /></body></html>"
        )
        with mock_urlopen(malformed):
            with pytest.raises(NormalizationError, match="body text was empty"):
                adapter.retrieve_section(_make_ref("1-1-10"))
