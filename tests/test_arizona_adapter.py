"""Tests for ArizonaAdapter.

Arizona is a server-rendered HTML source (the official Arizona Legislature
publication of the Arizona Revised Statutes at azleg.gov). Three structural
levels (Title -> Chapter -> Section) map onto the framework model:
``TitleRef.identifier`` is the title number (e.g. ``"28"``);
``ChapterRef.identifier`` is the chapter number (e.g. ``"1"``); and
``SectionRef.identifier`` is the full ``{title}-{section}`` citation (e.g.
``"28-101"``, including compound sections like ``"28-622.01"``).

Arizona chapters have no page of their own, so both chapter and section
listing are read from the title detail page (``/arsDetail/?title={N}``).
Section pages are one clean file per section at
``/ars/{title}/{file}.htm``, where the file name follows the rule
``28-101`` -> ``00101.htm`` and ``28-622.01`` -> ``00622-01.htm``.

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against **REAL captured Arizona HTML**: verbatim slices
of the official azleg.gov pages, captured live on Aug 15, 2026 and stored
under ``tests/fixtures/az_*``:

* ``az_arstitle.html`` -- the title list page (all 47 linked titles).
* ``az_arsdetail_28.html`` -- the Title 28 detail page (29 chapters, 1674
  section pairs, including compound ``28-622.01``).
* ``az_section_28-101.html`` -- section 28-101 "Definitions" (a long
  definitional body).
* ``az_section_28-622.01.html`` -- compound section 28-622.01 (a short
  body).

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

from state_statutes_mcp.adapters.arizona.adapter import ArizonaAdapter
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

# --- REAL fixtures: verbatim slices of the official Arizona Legislature
# --- pages captured live on Aug 15, 2026. NOT synthetic.
FIXTURES = Path(__file__).parent / "fixtures"

REAL_ARSTITLE_HTML = (FIXTURES / "az_arstitle.html").read_text(encoding="latin-1")
REAL_ARSDETAIL_28_HTML = (FIXTURES / "az_arsdetail_28.html").read_text(
    encoding="latin-1"
)
REAL_SEC28_101_HTML = (FIXTURES / "az_section_28-101.html").read_text(
    encoding="latin-1"
)
REAL_SEC28_62201_HTML = (FIXTURES / "az_section_28-622.01.html").read_text(
    encoding="latin-1"
)

BASE = "https://www.azleg.gov"

ARSTITLE_URL = f"{BASE}/arstitle/"
ARSDETAIL_28_URL = f"{BASE}/arsDetail/?title=28"
SEC28_101_URL = f"{BASE}/ars/28/00101.htm"
SEC28_102_URL = f"{BASE}/ars/28/00102.htm"
SEC28_62201_URL = f"{BASE}/ars/28/00622-01.htm"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _title_ref() -> TitleRef:
    return TitleRef(state_code="AZ", identifier="28")


def _chapter_ref() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="1")


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


def _serve_all() -> dict[str, str]:
    return {
        ARSTITLE_URL: REAL_ARSTITLE_HTML,
        ARSDETAIL_28_URL: REAL_ARSDETAIL_28_HTML,
        SEC28_101_URL: REAL_SEC28_101_HTML,
        SEC28_62201_URL: REAL_SEC28_62201_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert ArizonaAdapter.__abstractmethods__ == frozenset()
        adapter = ArizonaAdapter()
        assert adapter.state_code == "AZ"
        assert adapter.state_name == "Arizona"


class TestSectionFilename:
    def test_simple_section(self) -> None:
        assert ArizonaAdapter._section_filename("28-101") == "00101.htm"

    def test_compound_section(self) -> None:
        assert ArizonaAdapter._section_filename("28-622.01") == "00622-01.htm"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = ArizonaAdapter()

    def test_title_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_title_ref())
            == "https://www.azleg.gov/arsDetail/?title=28"
        )

    def test_chapter_ref_url_is_title_detail(self) -> None:
        # Chapters have no page of their own; the title detail page is the
        # closest real resource.
        assert (
            self.adapter.build_url(_chapter_ref())
            == "https://www.azleg.gov/arsDetail/?title=28"
        )

    def test_section_ref_url_simple(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("28-101"))
            == "https://www.azleg.gov/ars/28/00101.htm"
        )

    def test_section_ref_url_compound(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("28-622.01"))
            == "https://www.azleg.gov/ars/28/00622-01.htm"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def test_returns_all_linked_titles(self) -> None:
        adapter = ArizonaAdapter()
        with mock_urlopen_serving({ARSTITLE_URL: REAL_ARSTITLE_HTML}):
            titles = adapter.list_titles()

        assert len(titles) == 47
        first = titles[0]
        assert first.level == HierarchyLevel.TITLE
        assert first.identifier == "1"
        assert first.name == "General Provision"
        assert first.ref.state_code == "AZ"
        identifiers = [node.identifier for node in titles]
        assert "28" in identifiers
        # Repealed Title 2 (no link) and the "All" search row are excluded.
        assert "2" not in identifiers
        assert "0" not in identifiers
        assert len(set(identifiers)) == 47

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = ArizonaAdapter()
        with mock_urlopen("<html><body>no titles here</body></html>"):
            with pytest.raises(AdapterUnavailableError, match="no usable title"):
                adapter.list_titles()

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = ArizonaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_titles()


class TestListChapters:
    def test_returns_chapters_from_title_detail(self) -> None:
        adapter = ArizonaAdapter()
        with mock_urlopen_serving({ARSDETAIL_28_URL: REAL_ARSDETAIL_28_HTML}):
            chapters = adapter.list_chapters(_title_ref())

        assert len(chapters) == 29
        first = chapters[0]
        assert first.level == HierarchyLevel.CHAPTER
        assert first.identifier == "1"
        assert first.name == "DEFINITIONS, PENALTIES AND GENERAL PROVISIONS"
        assert first.ref.title.identifier == "28"
        assert first.ref.state_code == "AZ"
        identifiers = [node.identifier for node in chapters]
        assert "3" in identifiers
        assert len(set(identifiers)) == 29

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = ArizonaAdapter()
        with mock_urlopen_error(_http_error(ARSDETAIL_28_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_chapters(_title_ref())

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = ArizonaAdapter()
        with mock_urlopen("<html><body>no chapters</body></html>"):
            with pytest.raises(AdapterUnavailableError, match="no usable chapter"):
                adapter.list_chapters(_title_ref())


class TestListSections:
    def test_returns_sections_for_chapter(self) -> None:
        adapter = ArizonaAdapter()
        with mock_urlopen_serving({ARSDETAIL_28_URL: REAL_ARSDETAIL_28_HTML}):
            sections = adapter.list_sections(_chapter_ref())

        identifiers = [node.identifier for node in sections]
        assert identifiers[0] == "28-101"
        assert len(sections) == 7
        first = sections[0]
        assert first.level == HierarchyLevel.SECTION
        assert first.name == "Definitions"
        assert first.ref.chapter.identifier == "1"
        assert first.ref.state_code == "AZ"

    def test_compound_section_appears_in_its_chapter(self) -> None:
        adapter = ArizonaAdapter()
        chapter = ChapterRef(title=_title_ref(), identifier="3")
        with mock_urlopen_serving({ARSDETAIL_28_URL: REAL_ARSDETAIL_28_HTML}):
            sections = adapter.list_sections(chapter)
        identifiers = [node.identifier for node in sections]
        assert "28-622.01" in identifiers

    def test_sections_are_scoped_to_the_chapter(self) -> None:
        adapter = ArizonaAdapter()
        with mock_urlopen_serving({ARSDETAIL_28_URL: REAL_ARSDETAIL_28_HTML}):
            sections = adapter.list_sections(_chapter_ref())
        # None of chapter 1's sections may bleed in from other chapters.
        for node in sections:
            assert node.identifier.startswith("28-1")

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = ArizonaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_sections(_chapter_ref())


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = ArizonaAdapter()

    def test_happy_path(self) -> None:
        parsed = ParsedDocument(
            raw_citation="A.R.S. § 28-101",
            heading="Definitions",
            text='In this title, unless the context otherwise requires:\n1. "Alcohol"',
            amendment_notes=None,
            source_url="https://www.azleg.gov/ars/28/00101.htm",
            retrieved_at=None,
        )
        section = self.adapter.normalize(parsed, _make_ref("28-101"))

        assert section.citation.raw == "A.R.S. § 28-101"
        assert section.citation.state_code == "AZ"
        assert section.heading == "Definitions"
        assert section.text.startswith("In this title")
        assert section.amendment_notes is None
        assert section.status.value == "unknown"

    def test_wrong_state_raises_normalization_error(self) -> None:
        parsed = ParsedDocument(
            raw_citation="A.R.S. § 28-101",
            heading=None,
            text="body",
            amendment_notes=None,
            source_url=None,
            retrieved_at=None,
        )
        other_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="NM", identifier="28"), identifier="1"
            ),
            identifier="28-101",
        )
        with pytest.raises(NormalizationError, match="expected 'AZ'"):
            self.adapter.normalize(parsed, other_ref)

    def test_ref_mismatch_raises(self) -> None:
        parsed = ParsedDocument(
            raw_citation="A.R.S. § 28-102",
            heading=None,
            text="body",
            amendment_notes=None,
            source_url=None,
            retrieved_at=None,
        )
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, _make_ref("28-101"))


class TestRetrieveSection:
    def test_simple_section(self) -> None:
        adapter = ArizonaAdapter()
        with mock_urlopen_serving(_serve_all()):
            section = adapter.retrieve_section(_make_ref("28-101"))

        assert section.ref.identifier == "28-101"
        assert section.citation.raw == "A.R.S. § 28-101"
        assert section.heading == "Definitions"
        assert section.text.startswith("In this title, unless the context")
        assert '"Alcohol" means any substance' in section.text
        assert section.amendment_notes is None
        assert section.source_url == SEC28_101_URL
        assert section.status.value == "unknown"
        assert section.retrieved_at is not None

    def test_compound_section(self) -> None:
        adapter = ArizonaAdapter()
        ref = SectionRef(
            chapter=ChapterRef(title=_title_ref(), identifier="3"),
            identifier="28-622.01",
        )
        with mock_urlopen_serving(_serve_all()):
            section = adapter.retrieve_section(ref)

        assert section.ref.identifier == "28-622.01"
        assert section.citation.raw == "A.R.S. § 28-622.01"
        assert section.heading.startswith("Unlawful flight from pursuing")
        assert section.text.startswith(
            "A driver of a motor vehicle who wilfully flees"
        )
        assert section.source_url == SEC28_62201_URL

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = ArizonaAdapter()
        with mock_urlopen_error(_http_error(SEC28_101_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.retrieve_section(_make_ref("28-101"))

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = ArizonaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.retrieve_section(_make_ref("28-101"))

    def test_citation_number_mismatch_raises(self) -> None:
        adapter = ArizonaAdapter()
        # A section whose page names a different number than requested.
        wrong_ref = _make_ref("28-102")
        with mock_urlopen_serving({SEC28_102_URL: REAL_SEC28_101_HTML}):
            with pytest.raises(RefMismatchError, match="does not match the citation"):
                adapter.retrieve_section(wrong_ref)

    def test_missing_heading_raises_normalization_error(self) -> None:
        adapter = ArizonaAdapter()
        with mock_urlopen("<html><body><p>no heading here</p></body></html>"):
            with pytest.raises(NormalizationError, match="no heading paragraph"):
                adapter.retrieve_section(_make_ref("28-101"))

    def test_empty_body_raises_normalization_error(self) -> None:
        adapter = ArizonaAdapter()
        malformed = (
            '<html><body><p><font color=GREEN>28-101.</font> '
            "<font color=PURPLE><u>Definitions</u></font></p></body></html>"
        )
        with mock_urlopen(malformed):
            with pytest.raises(NormalizationError, match="body text was empty"):
                adapter.retrieve_section(_make_ref("28-101"))
