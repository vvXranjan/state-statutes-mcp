"""Tests for MinnesotaAdapter.

Minnesota is a server-rendered HTML source (the official Revisor of
Statutes publication of Minnesota Statutes at revisor.mn.gov). The site
has no formal title level: chapters are grouped directly into 105 official
"Parts". To fit the framework's three-level ref model, the adapter maps
each Part onto a synthetic ``TitleRef`` whose identifier is the part name
(e.g. ``"DATA PRACTICES"``) -- an adapter-internal mapping, not a
framework change. Chapter identifiers may be numeric (``13``) or lettered
(``3C``, ``13A``); ``SectionRef.identifier`` is the full dotted
``{chapter}.{section}`` citation (e.g. ``"3C.12"``).

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against **REAL captured Minnesota HTML**: verbatim
slices of the official revisor.mn.gov/statutes pages, captured live on
Aug 15, 2026 and stored under ``tests/fixtures/mn_*``:

* ``mn_statutes_home_parts.html`` -- the statutes root page (all 105
  Parts).
* ``mn_part_data_practices.html`` -- the DATA PRACTICES part page
  (chapters 13, 13A, 13B, 13C).
* ``mn_chapter_3C.html`` -- the Chapter 3C TOC page (15 sections,
  including dotted ``3C.035``).
* ``mn_section_3C12.html`` -- section 3C.12 (multi-subdivision body with
  a long history block).
* ``mn_section_3E01.html`` -- section 3E.01 (a short bare-``<p>`` body).

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

from state_statutes_mcp.adapters.minnesota.adapter import MinnesotaAdapter
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

# --- REAL fixtures: verbatim slices of the official Revisor of Minnesota
# --- statutes pages captured live on Aug 15, 2026. NOT synthetic.
FIXTURES = Path(__file__).parent / "fixtures"

REAL_HOME_PARTS_HTML = (FIXTURES / "mn_statutes_home_parts.html").read_text(
    encoding="utf-8"
)
REAL_PART_DATA_PRACTICES_HTML = (
    FIXTURES / "mn_part_data_practices.html"
).read_text(encoding="utf-8")
REAL_CH3C_HTML = (FIXTURES / "mn_chapter_3C.html").read_text(encoding="utf-8")
REAL_SEC3C12_HTML = (FIXTURES / "mn_section_3C12.html").read_text(encoding="utf-8")
REAL_SEC3E01_HTML = (FIXTURES / "mn_section_3E01.html").read_text(encoding="utf-8")

BASE = "https://www.revisor.mn.gov/statutes"

HOME_URL = f"{BASE}/"
PART_DATA_PRACTICES_URL = f"{BASE}/part/DATA+PRACTICES"
CH3C_URL = f"{BASE}/cite/3C"
SEC3C12_URL = f"{BASE}/cite/3C.12"
SEC3C13_URL = f"{BASE}/cite/3C.13"
SEC3E01_URL = f"{BASE}/cite/3E.01"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _title_ref() -> TitleRef:
    return TitleRef(state_code="MN", identifier="DATA PRACTICES")


def _chapter_ref() -> ChapterRef:
    return ChapterRef(title=TitleRef(state_code="MN", identifier="LEGISLATURE"), identifier="3C")


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


def _serve_all() -> dict[str, str]:
    return {
        HOME_URL: REAL_HOME_PARTS_HTML,
        PART_DATA_PRACTICES_URL: REAL_PART_DATA_PRACTICES_HTML,
        CH3C_URL: REAL_CH3C_HTML,
        SEC3C12_URL: REAL_SEC3C12_HTML,
        SEC3E01_URL: REAL_SEC3E01_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert MinnesotaAdapter.__abstractmethods__ == frozenset()
        adapter = MinnesotaAdapter()
        assert adapter.state_code == "MN"
        assert adapter.state_name == "Minnesota"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = MinnesotaAdapter()

    def test_title_ref_url_is_part_page(self) -> None:
        assert (
            self.adapter.build_url(_title_ref())
            == "https://www.revisor.mn.gov/statutes/part/DATA+PRACTICES"
        )

    def test_title_ref_url_quote_plus_comma(self) -> None:
        ref = TitleRef(state_code="MN", identifier="JURISDICTION, CIVIL DIVISIONS")
        assert self.adapter.build_url(ref) == (
            "https://www.revisor.mn.gov/statutes/part/"
            "JURISDICTION%2C+CIVIL+DIVISIONS"
        )

    def test_chapter_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_chapter_ref())
            == "https://www.revisor.mn.gov/statutes/cite/3C"
        )

    def test_section_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("3C.12"))
            == "https://www.revisor.mn.gov/statutes/cite/3C.12"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def test_returns_all_parts_in_document_order(self) -> None:
        adapter = MinnesotaAdapter()
        with mock_urlopen_serving({HOME_URL: REAL_HOME_PARTS_HTML}):
            titles = adapter.list_titles()

        assert len(titles) == 105
        first = titles[0]
        assert first.level == HierarchyLevel.TITLE
        assert first.identifier == "JURISDICTION, CIVIL DIVISIONS"
        assert first.name == "JURISDICTION, CIVIL DIVISIONS"
        assert first.ref.state_code == "MN"
        # The lettered part range row (DATA PRACTICES) is present too.
        identifiers = [node.identifier for node in titles]
        assert "DATA PRACTICES" in identifiers
        assert "LEGISLATURE" in identifiers
        # 105 unique part names.
        assert len(set(identifiers)) == 105

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = MinnesotaAdapter()
        with mock_urlopen("<html><body>no parts here</body></html>"):
            with pytest.raises(AdapterUnavailableError, match="no usable part"):
                adapter.list_titles()

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = MinnesotaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_titles()


class TestListChapters:
    def test_returns_chapters_from_part_page(self) -> None:
        adapter = MinnesotaAdapter()
        with mock_urlopen_serving({PART_DATA_PRACTICES_URL: REAL_PART_DATA_PRACTICES_HTML}):
            chapters = adapter.list_chapters(_title_ref())

        assert [node.identifier for node in chapters] == ["13", "13A", "13B", "13C"]
        first = chapters[0]
        assert first.level == HierarchyLevel.CHAPTER
        assert first.name == "GOVERNMENT DATA PRACTICES"
        assert first.ref.title.identifier == "DATA PRACTICES"
        assert first.ref.state_code == "MN"

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = MinnesotaAdapter()
        with mock_urlopen_error(_http_error(PART_DATA_PRACTICES_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_chapters(_title_ref())

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = MinnesotaAdapter()
        with mock_urlopen("<html><body>no chapters</body></html>"):
            with pytest.raises(AdapterUnavailableError, match="no usable chapter"):
                adapter.list_chapters(_title_ref())


class TestListSections:
    def test_returns_sections_from_chapter_toc(self) -> None:
        adapter = MinnesotaAdapter()
        with mock_urlopen_serving({CH3C_URL: REAL_CH3C_HTML}):
            sections = adapter.list_sections(_chapter_ref())

        identifiers = [node.identifier for node in sections]
        assert identifiers[0] == "3C.01"
        assert "3C.035" in identifiers
        assert identifiers[-1] == "3C.20"
        assert len(sections) == 18
        assert "3C.056" in identifiers
        first = sections[0]
        assert first.level == HierarchyLevel.SECTION
        assert first.name == "APPOINTMENT OF REVISOR."
        assert first.ref.chapter.identifier == "3C"
        assert first.ref.state_code == "MN"

        by_id = {node.identifier: node for node in sections}
        assert "Repealed" in by_id["3C.056"].name

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = MinnesotaAdapter()
        with mock_urlopen_error(_http_error(CH3C_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_sections(_chapter_ref())

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = MinnesotaAdapter()
        with mock_urlopen("<html><body>no sections</body></html>"):
            with pytest.raises(AdapterUnavailableError, match="no usable section"):
                adapter.list_sections(_chapter_ref())


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = MinnesotaAdapter()

    def test_happy_path(self) -> None:
        parsed = ParsedDocument(
            raw_citation="Minn. Stat. § 3C.12",
            heading="SALE AND DISTRIBUTION OF STATUTES AND LAWS.",
            text="The revisor shall determine how many copies ...",
            amendment_notes="1984 c 480 s 12; 1984 c 654 art 5 s 58",
            source_url="https://www.revisor.mn.gov/statutes/cite/3C.12",
            retrieved_at=None,
        )
        section = self.adapter.normalize(parsed, _make_ref("3C.12"))

        assert section.citation.raw == "Minn. Stat. § 3C.12"
        assert section.citation.state_code == "MN"
        assert section.heading == "SALE AND DISTRIBUTION OF STATUTES AND LAWS."
        assert section.text.startswith("The revisor shall determine")
        assert section.amendment_notes.startswith("1984 c 480 s 12")
        assert section.status.value == "unknown"

    def test_wrong_state_raises_normalization_error(self) -> None:
        parsed = ParsedDocument(
            raw_citation="Minn. Stat. § 3C.12",
            heading=None,
            text="body",
            amendment_notes=None,
            source_url=None,
            retrieved_at=None,
        )
        other_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="WI", identifier="x"), identifier="1"
            ),
            identifier="3C.12",
        )
        with pytest.raises(NormalizationError, match="expected 'MN'"):
            self.adapter.normalize(parsed, other_ref)

    def test_ref_mismatch_raises(self) -> None:
        parsed = ParsedDocument(
            raw_citation="Minn. Stat. § 3C.13",
            heading=None,
            text="body",
            amendment_notes=None,
            source_url=None,
            retrieved_at=None,
        )
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, _make_ref("3C.12"))


class TestRetrieveSection:
    def test_multi_subdivision_section(self) -> None:
        adapter = MinnesotaAdapter()
        with mock_urlopen_serving(_serve_all()):
            section = adapter.retrieve_section(_make_ref("3C.12"))

        assert section.ref.identifier == "3C.12"
        assert section.citation.raw == "Minn. Stat. § 3C.12"
        assert section.heading == "SALE AND DISTRIBUTION OF STATUTES AND LAWS."
        assert "Subdivision 1. Number of copies printed." in section.text
        assert "The revisor shall determine how many copies" in section.text
        assert section.amendment_notes is not None
        assert section.amendment_notes.startswith("1984 c 480 s 12 ;")
        assert "1984 c 654 art 5 s 58 ;" in section.amendment_notes
        assert section.source_url == SEC3C12_URL
        assert section.status.value == "unknown"
        assert section.retrieved_at is not None

    def test_simple_body_section(self) -> None:
        adapter = MinnesotaAdapter()
        ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="MN", identifier="LEGISLATURE"),
                identifier="3E",
            ),
            identifier="3E.01",
        )
        with mock_urlopen_serving(_serve_all()):
            section = adapter.retrieve_section(ref)

        assert section.ref.identifier == "3E.01"
        assert section.heading == "SHORT TITLE."
        assert (
            'This chapter may be cited as the "Uniform Electronic Legal '
            "Material Act.\"" in section.text
        )
        assert section.amendment_notes == "2013 c 7 s 1 ,11"

    def test_heading_prefix_is_stripped(self) -> None:
        adapter = MinnesotaAdapter()
        with mock_urlopen_serving(_serve_all()):
            section = adapter.retrieve_section(_make_ref("3C.12"))
        assert not section.heading.startswith("3C.12 ")

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = MinnesotaAdapter()
        with mock_urlopen_error(_http_error(SEC3C12_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.retrieve_section(_make_ref("3C.12"))

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = MinnesotaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.retrieve_section(_make_ref("3C.12"))

    def test_chapter_anchor_mismatch_raises(self) -> None:
        adapter = MinnesotaAdapter()
        wrong_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="MN", identifier="LEGISLATURE"),
                identifier="3E",
            ),
            identifier="3C.12",
        )
        with mock_urlopen_serving(_serve_all()):
            with pytest.raises(RefMismatchError, match="does not match the chapter"):
                adapter.retrieve_section(wrong_ref)

    def test_section_anchor_mismatch_raises(self) -> None:
        adapter = MinnesotaAdapter()
        wrong_ref = _make_ref("3C.13")
        with mock_urlopen_serving({SEC3C13_URL: REAL_SEC3C12_HTML}):
            with pytest.raises(RefMismatchError, match="does not match the section"):
                adapter.retrieve_section(wrong_ref)

    def test_missing_heading_raises_normalization_error(self) -> None:
        adapter = MinnesotaAdapter()
        malformed = "<html><body><h2>Chapter 3C</h2><h2>Section 3C.12</h2></body></html>"
        with mock_urlopen(malformed):
            with pytest.raises(NormalizationError, match="no heading element"):
                adapter.retrieve_section(_make_ref("3C.12"))

    def test_empty_body_raises_normalization_error(self) -> None:
        adapter = MinnesotaAdapter()
        malformed = (
            "<html><body><h2>Chapter 3C</h2><h2>Section 3C.12</h2>"
            '<h1 class="shn">3C.12 TITLE.</h1></body></html>'
        )
        with mock_urlopen(malformed):
            with pytest.raises(NormalizationError, match="body text was empty"):
                adapter.retrieve_section(_make_ref("3C.12"))
