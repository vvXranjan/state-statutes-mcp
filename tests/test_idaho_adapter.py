"""Tests for IdahoAdapter.

Idaho is a server-rendered HTML source (the official Idaho Legislature
publication of the Idaho Code at legislature.idaho.gov). Three structural
levels (Title -> Chapter -> Section) map 1:1 onto the framework model;
titles are numbered 1-74; chapter identifiers are numeric (1, 2, ... 91
within Title 18); section identifiers are the full ``{title}-{chapter}
{local}`` form and may carry a trailing letter (``18-4004A``).

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against **REAL captured Idaho HTML**: verbatim slices
of the official legislature.idaho.gov pages, captured through a Wayback
Machine snapshot of the official host (timestamp 20260712203433, the live
host being unreachable from this environment) and stored under
``tests/fixtures/id_*``:

* ``id_statutes_index.html`` -- the statutes index page (all 74 titles).
* ``id_title18.html`` -- the Title 18 page (82 chapters).
* ``id_ch40.html`` -- the Chapter 40 page (16 sections, including the
  lettered ``18-4004A``).
* ``id_section_18-4001.html`` -- section 18-4001 "Murder defined." (a plain
  single-paragraph body with a history line).
* ``id_section_18-4003.html`` -- section 18-4003 "Degrees of murder." (a
  lettered-subsection body ``(a)``-``(g)`` with a history line).

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

from state_statutes_mcp.adapters.idaho.adapter import IdahoAdapter
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

# --- REAL fixtures: verbatim slices of the official Idaho Legislature
# --- statutes pages captured through a Wayback Machine snapshot of
# --- legislature.idaho.gov (timestamp 20260712203433). NOT synthetic.
FIXTURES = Path(__file__).parent / "fixtures"

REAL_INDEX_HTML = (FIXTURES / "id_statutes_index.html").read_text(
    encoding="utf-8"
)
REAL_TITLE18_HTML = (FIXTURES / "id_title18.html").read_text(encoding="utf-8")
REAL_CH40_HTML = (FIXTURES / "id_ch40.html").read_text(encoding="utf-8")
REAL_SEC18_4001_HTML = (FIXTURES / "id_section_18-4001.html").read_text(
    encoding="utf-8"
)
REAL_SEC18_4003_HTML = (FIXTURES / "id_section_18-4003.html").read_text(
    encoding="utf-8"
)

BASE = "https://legislature.idaho.gov"

INDEX_URL = f"{BASE}/statutesrules/idstat/"
TITLE18_URL = f"{BASE}/statutesrules/idstat/Title18"
CH40_URL = f"{BASE}/statutesrules/idstat/Title18/T18CH40"
SEC18_4001_URL = f"{BASE}/statutesrules/idstat/Title18/T18CH40/SECT18-4001"
SEC18_4003_URL = f"{BASE}/statutesrules/idstat/Title18/T18CH40/SECT18-4003"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _title_ref() -> TitleRef:
    return TitleRef(state_code="ID", identifier="18")


def _chapter_ref() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="40")


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


def _serve_all() -> dict[str, str]:
    return {
        INDEX_URL: REAL_INDEX_HTML,
        TITLE18_URL: REAL_TITLE18_HTML,
        CH40_URL: REAL_CH40_HTML,
        SEC18_4001_URL: REAL_SEC18_4001_HTML,
        SEC18_4003_URL: REAL_SEC18_4003_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert IdahoAdapter.__abstractmethods__ == frozenset()
        adapter = IdahoAdapter()
        assert adapter.state_code == "ID"
        assert adapter.state_name == "Idaho"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = IdahoAdapter()

    def test_title_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_title_ref())
            == "https://legislature.idaho.gov/statutesrules/idstat/Title18"
        )

    def test_chapter_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_chapter_ref())
            == "https://legislature.idaho.gov/statutesrules/idstat/"
            "Title18/T18CH40"
        )

    def test_section_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("18-4001"))
            == "https://legislature.idaho.gov/statutesrules/idstat/"
            "Title18/T18CH40/SECT18-4001"
        )

    def test_section_ref_url_lettered_identifier(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("18-4004A"))
            == "https://legislature.idaho.gov/statutesrules/idstat/"
            "Title18/T18CH40/SECT18-4004A"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def test_returns_all_74_titles_from_index(self) -> None:
        adapter = IdahoAdapter()
        with mock_urlopen_serving({INDEX_URL: REAL_INDEX_HTML}):
            titles = adapter.list_titles()

        assert len(titles) == 74
        assert titles[0].identifier == "1"
        assert titles[-1].identifier == "74"
        assert titles[0].name == "COURTS AND COURT OFFICIALS"
        assert all(n.level == HierarchyLevel.TITLE for n in titles)
        assert all(n.ref.state_code == "ID" for n in titles)

    def test_title_18_identifier_and_name(self) -> None:
        adapter = IdahoAdapter()
        with mock_urlopen_serving({INDEX_URL: REAL_INDEX_HTML}):
            titles = adapter.list_titles()
        by_id = {n.identifier: n.name for n in titles}
        assert by_id["18"] == "CRIMES AND PUNISHMENTS"

    def test_numeric_order(self) -> None:
        adapter = IdahoAdapter()
        with mock_urlopen_serving({INDEX_URL: REAL_INDEX_HTML}):
            titles = adapter.list_titles()
        identifiers = [n.identifier for n in titles]
        assert identifiers == sorted(identifiers, key=int)

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = IdahoAdapter()
        with mock_urlopen_error(_http_error(INDEX_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_titles()

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = IdahoAdapter()
        with mock_urlopen("<html><body>no titles</body></html>"):
            with pytest.raises(AdapterUnavailableError, match="no usable title"):
                adapter.list_titles()

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = IdahoAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_titles()


class TestListChapters:
    def test_returns_all_chapters_of_title_18(self) -> None:
        adapter = IdahoAdapter()
        with mock_urlopen_serving({TITLE18_URL: REAL_TITLE18_HTML}):
            chapters = adapter.list_chapters(_title_ref())

        assert len(chapters) == 82
        assert chapters[0].identifier == "1"
        assert chapters[-1].identifier == "91"
        assert chapters[0].name == "PRELIMINARY PROVISIONS"
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)
        assert all(n.ref.title == _title_ref() for n in chapters)

    def test_chapter_40_name(self) -> None:
        adapter = IdahoAdapter()
        with mock_urlopen_serving({TITLE18_URL: REAL_TITLE18_HTML}):
            chapters = adapter.list_chapters(_title_ref())
        by_id = {n.identifier: n.name for n in chapters}
        assert by_id["40"] == "HOMICIDE"

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = IdahoAdapter()
        title_ref = TitleRef(state_code="ID", identifier="999")
        url = "https://legislature.idaho.gov/statutesrules/idstat/Title999"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                adapter.list_chapters(title_ref)

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = IdahoAdapter()
        with mock_urlopen("<html><body>no chapters</body></html>"):
            with pytest.raises(AdapterUnavailableError, match="no usable chapter"):
                adapter.list_chapters(_title_ref())


class TestListSections:
    def test_returns_sections_of_chapter_40(self) -> None:
        adapter = IdahoAdapter()
        with mock_urlopen_serving({CH40_URL: REAL_CH40_HTML}):
            sections = adapter.list_sections(_chapter_ref())

        assert len(sections) == 16
        assert sections[0].identifier == "18-4001"
        assert sections[0].name == "MURDER DEFINED."
        assert sections[-1].identifier == "18-4017"
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == _chapter_ref() for n in sections)

    def test_lettered_section_identifier(self) -> None:
        adapter = IdahoAdapter()
        with mock_urlopen_serving({CH40_URL: REAL_CH40_HTML}):
            sections = adapter.list_sections(_chapter_ref())
        by_id = {n.identifier: n.name for n in sections}
        assert by_id["18-4004A"] == "NOTICE OF INTENT TO SEEK DEATH PENALTY."
        assert by_id["18-4004"] == "PUNISHMENT FOR MURDER."

    def test_numeric_order(self) -> None:
        adapter = IdahoAdapter()
        with mock_urlopen_serving({CH40_URL: REAL_CH40_HTML}):
            sections = adapter.list_sections(_chapter_ref())
        identifiers = [n.identifier for n in sections]
        assert identifiers[3] == "18-4004"
        assert identifiers[4] == "18-4004A"
        assert identifiers[5] == "18-4005"

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = IdahoAdapter()
        chapter_ref = ChapterRef(title=_title_ref(), identifier="999")
        url = "https://legislature.idaho.gov/statutesrules/idstat/Title18/T18CH999"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                adapter.list_sections(chapter_ref)

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = IdahoAdapter()
        with mock_urlopen_serving({CH40_URL: "<html><body>none</body></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable section"):
                adapter.list_sections(_chapter_ref())


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = IdahoAdapter()

    def test_plain_section_full_retrieval(self) -> None:
        ref = _make_ref("18-4001")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Idaho Code § 18-4001"
        assert section.citation.state_code == "ID"
        assert section.ref == ref
        assert section.heading == "Murder defined."
        assert section.text.startswith("Murder is the unlawful killing")
        assert "human embryo or fetus" in section.text
        assert section.amendment_notes == (
            "[18-4001, added 1972, ch. 336, sec. 1, p. 928; am. 1977, "
            "ch. 154, sec. 1, p. 390; am. 2002, ch. 330, sec. 1, p. 935.]"
        )
        assert section.status.value == "unknown"
        assert section.source_url == SEC18_4001_URL
        assert section.retrieved_at is not None

    def test_subsectioned_section(self) -> None:
        ref = _make_ref("18-4003")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Idaho Code § 18-4003"
        assert section.heading == "Degrees of murder."
        assert section.text.startswith("(a) All murder which is perpetrated")
        assert "(b)" in section.text
        assert "(c)" in section.text
        assert section.amendment_notes is not None
        assert section.amendment_notes.startswith("[18-4003, added 1972")
        assert "am. 2002, ch. 222" in section.amendment_notes
        assert section.status.value == "unknown"
        assert section.source_url == SEC18_4003_URL

    def test_missing_section_404_raises_ref_not_found(self) -> None:
        ref = _make_ref("18-9999")
        url = (
            "https://legislature.idaho.gov/statutesrules/idstat/"
            "Title18/T18CH40/SECT18-9999"
        )
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable_error(self) -> None:
        ref = _make_ref("18-4001")
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestParseEdgeCases:
    def setup_method(self) -> None:
        self.adapter = IdahoAdapter()

    def test_title_mismatch_raises_ref_mismatch_error(self) -> None:
        # Request title 1 but the section page belongs to title 18.
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="ID", identifier="1"),
                identifier="40",
            ),
            identifier="18-4001",
        )
        url = (
            "https://legislature.idaho.gov/statutesrules/idstat/"
            "Title1/T1CH40/SECT18-4001"
        )
        with mock_urlopen_serving({url: REAL_SEC18_4001_HTML}):
            with pytest.raises(RefMismatchError, match="does not match the title"):
                self.adapter.retrieve_section(foreign_ref)

    def test_chapter_mismatch_raises_ref_mismatch_error(self) -> None:
        # Request chapter 41 but the section page belongs to chapter 40.
        foreign_ref = SectionRef(
            chapter=ChapterRef(title=_title_ref(), identifier="41"),
            identifier="18-4001",
        )
        url = (
            "https://legislature.idaho.gov/statutesrules/idstat/"
            "Title18/T18CH41/SECT18-4001"
        )
        with mock_urlopen_serving({url: REAL_SEC18_4001_HTML}):
            with pytest.raises(RefMismatchError, match="does not match the chapter"):
                self.adapter.retrieve_section(foreign_ref)

    def test_section_id_mismatch_raises_ref_mismatch_error(self) -> None:
        # Request 18-4002 but the page's title tag is 18-4001.
        foreign_ref = _make_ref("18-4002")
        url = (
            "https://legislature.idaho.gov/statutesrules/idstat/"
            "Title18/T18CH40/SECT18-4002"
        )
        with mock_urlopen_serving({url: REAL_SEC18_4001_HTML}):
            with pytest.raises(RefMismatchError, match="does not match the section"):
                self.adapter.retrieve_section(foreign_ref)

    def test_missing_heading_raises_normalization_error(self) -> None:
        ref = _make_ref("18-4001")
        html = (
            '<div class="breadcrumb-gray-text">'
            '<a title="Browse to: Title 18">Title 18</a>'
            '<a title="Browse to: Chapter 40">Chapter 40</a>'
            "<li>Section 18-4001</li></div>"
            "<title>Section 18-4001 &#8211; Idaho State Legislature</title>"
            '<div style="...">TITLE 18 </div>'
            '<span class="f11s" style="font-family: Courier New;">18-4001.'
            "&nbsp;&nbsp;body text</span></div>"
            '<div style="...">'
            '<span style="font-size: 11pt; font-family: Courier New;">'
            "History:</span></div>"
        )
        with mock_urlopen_serving({SEC18_4001_URL: html}):
            with pytest.raises(NormalizationError, match="no heading element"):
                self.adapter.retrieve_section(ref)

    def test_empty_body_raises_normalization_error(self) -> None:
        ref = _make_ref("18-4001")
        html = (
            '<div class="breadcrumb-gray-text">'
            '<a title="Browse to: Title 18">Title 18</a>'
            '<a title="Browse to: Chapter 40">Chapter 40</a>'
            "<li>Section 18-4001</li></div>"
            "<title>Section 18-4001 &#8211; Idaho State Legislature</title>"
            '<div style="...">TITLE 18 </div>'
            '<span class="f11s" style="font-family: Courier New;">18-4001.'
            '&nbsp;&nbsp;<span style="text-transform: uppercase">'
            "Heading.&nbsp;</span></span></div>"
            '<div style="...">'
            '<span style="font-size: 11pt; font-family: Courier New;">'
            "History:</span></div>"
        )
        with mock_urlopen_serving({SEC18_4001_URL: html}):
            with pytest.raises(NormalizationError, match="body text was empty"):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = IdahoAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("18-4001")
        parsed = ParsedDocument(
            raw_citation="Idaho Code § 18-4001",
            heading="Murder defined.",
            text="Murder is the unlawful killing ...",
            amendment_notes="[18-4001, added 1972, ch. 336, sec. 1, p. 928.]",
            source_url=SEC18_4001_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "Idaho Code § 18-4001"
        assert section.citation.state_code == "ID"
        assert section.heading == "Murder defined."
        assert section.text == "Murder is the unlawful killing ..."
        assert section.amendment_notes == "[18-4001, added 1972, ch. 336, sec. 1, p. 928.]"
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="OH", identifier="x"), identifier="1"
            ),
            identifier="18-4001",
        )
        parsed = ParsedDocument(
            raw_citation="Idaho Code § 18-4001",
            text="Some text.",
        )
        with pytest.raises(NormalizationError, match="expected 'ID'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("18-4001")
        parsed = ParsedDocument(
            raw_citation="Idaho Code § 18-4003",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)
