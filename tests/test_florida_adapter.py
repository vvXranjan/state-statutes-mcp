"""Tests for FloridaAdapter.

Florida is the framework's first **versioned** statute source: the official
site publishes the Florida Statutes as distinct per-year editions, and the
adapter pins the current published edition as an internal constant. Sections
have no per-section page; they live as ``<div class="Section">`` blocks
inside a chapter's ``/All`` document and are matched by their
``SectionNumber`` anchor.

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against **REAL captured Florida HTML**: a verbatim slice
of the official Chapter 775 ``/All`` document (sections 775.01, 775.021,
775.15), captured live from flsenate.gov on Aug 14, 2026 and stored in
``tests/fixtures/florida_chapter775_all.html``.

Home-page and title-page fixtures are **SYNTHETIC** — hand-written to match
the verified link structure documented in ``FloridaAdapter``'s module
docstring (title links ``/Laws/Statutes/2025/Title{N}/#Title{N}`` with
``descript`` names; chapter links ``/Laws/Statutes/2025/Chapter{N}`` with
``chDescript`` names). They are NOT saved real government fixtures.

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

from state_statutes_mcp.adapters.florida.adapter import FloridaAdapter
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

# --- REAL fixture: verbatim slice of the official Chapter 775 "/All"
# --- document captured live on Aug 14, 2026 (sections 775.01, 775.021,
# --- 775.15). NOT synthetic.
REAL_ALL_HTML = (
    Path(__file__).parent / "fixtures" / "florida_chapter775_all.html"
).read_text(encoding="utf-8")

# --- SYNTHETIC mock pages -- NOT real government fixtures. ---

# Home page: title links in a deliberately scrambled order, plus a
# constitution link the adapter must ignore.
SYNTHETIC_HOME_HTML = """
<html><body>
  <a href="/Laws/Statutes/2025/Title46/#Title46">
    <span id="Title46" class="title">Title XLVI</span>
    <span class="descript">CRIMES </span>
    <span class="chapterRange">(Ch. 775-899)</span>
  </a>
  <a href="/Laws/Statutes/2025/Title1/#Title1">
    <span id="Title1" class="title">Title I</span>
    <span class="descript">CONSTRUCTION OF STATUTES </span>
    <span class="chapterRange">(Ch. 1-2)</span>
  </a>
  <a href="/Laws/Statutes/2025/Title49/#Title49">
    <span id="Title49" class="title">Title XLIX</span>
    <span class="descript"> </span>
    <span class="chapterRange">(Ch. 1-2)</span>
  </a>
  <a href="/Laws/Constitution">The Florida Constitution</a>
</body></html>
"""

# Title 46 page: chapter links (scrambled order, plus a PDF link the
# adapter must ignore).
SYNTHETIC_TITLE_HTML = """
<html><body>
  <a href="/Laws/Statutes/2025/Chapter782">
    <span class="chTitle">
      Chapter 782
    </span>
    <span class="chDescript">- HOMICIDE</span>
  </a>
  <a href="/Laws/Statutes/2025/Chapter775">
    <span class="chTitle">
      Chapter 775
    </span>
    <span class="chDescript">- GENERAL PENALTIES; REGISTRATION OF CRIMINALS</span>
  </a>
  <a href="/Laws/Statutes/2025/Chapter1">
    <span class="chTitle">
      Chapter 1
    </span>
    <span class="chDescript">- CONSTRUCTION OF STATUTES</span>
  </a>
  <a href="/PublishedContent/Laws/Statutes/Links/Table_of_Section_Changes__2025_.pdf">PDF</a>
</body></html>
"""

HOME_URL = "https://www.flsenate.gov/Laws/Statutes/"
TITLE46_URL = "https://www.flsenate.gov/Laws/Statutes/2025/Title46"
C775_ALL_URL = "https://www.flsenate.gov/Laws/Statutes/2025/Chapter775/All"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _make_ref(section: str) -> SectionRef:
    return SectionRef(
        chapter=ChapterRef(
            title=TitleRef(state_code="FL", identifier="46"),
            identifier="775",
        ),
        identifier=section,
    )


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert FloridaAdapter.__abstractmethods__ == frozenset()
        adapter = FloridaAdapter()
        assert adapter.state_code == "FL"
        assert adapter.state_name == "Florida"


class TestEditionYear:
    def test_year_is_pinned_and_documented(self) -> None:
        assert FloridaAdapter.DEFAULT_YEAR == "2025"

    def test_year_appears_in_every_url(self) -> None:
        adapter = FloridaAdapter()
        title_ref = TitleRef(state_code="FL", identifier="46")
        chapter_ref = ChapterRef(title=title_ref, identifier="775")
        assert f"/{FloridaAdapter.DEFAULT_YEAR}/" in adapter.build_url(title_ref)
        assert f"/{FloridaAdapter.DEFAULT_YEAR}/" in adapter.build_url(chapter_ref)
        assert f"/{FloridaAdapter.DEFAULT_YEAR}/" in adapter.build_url(_make_ref("775.01"))


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = FloridaAdapter()

    def test_title_ref_url(self) -> None:
        ref = TitleRef(state_code="FL", identifier="46")
        assert (
            self.adapter.build_url(ref)
            == "https://www.flsenate.gov/Laws/Statutes/2025/Title46"
        )

    def test_chapter_ref_url(self) -> None:
        ref = ChapterRef(
            title=TitleRef(state_code="FL", identifier="46"), identifier="775"
        )
        assert (
            self.adapter.build_url(ref)
            == "https://www.flsenate.gov/Laws/Statutes/2025/Chapter775"
        )

    def test_section_ref_url_is_parent_chapter_all_document(self) -> None:
        ref = _make_ref("775.01")
        assert (
            self.adapter.build_url(ref)
            == "https://www.flsenate.gov/Laws/Statutes/2025/Chapter775/All"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestDiscovery:
    def setup_method(self) -> None:
        self.adapter = FloridaAdapter()

    def test_list_titles(self) -> None:
        with mock_urlopen(SYNTHETIC_HOME_HTML):
            titles = self.adapter.list_titles()

        assert [n.identifier for n in titles] == ["1", "46", "49"]
        assert [n.name for n in titles] == [
            "CONSTRUCTION OF STATUTES",
            "CRIMES",
            "49",
        ]
        assert all(n.level == HierarchyLevel.TITLE for n in titles)
        assert all(n.ref.state_code == "FL" for n in titles)

    def test_list_titles_no_title_links_raises(self) -> None:
        with mock_urlopen("<html><body>no titles here</body></html>"):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_titles_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_chapters(self) -> None:
        title_ref = TitleRef(state_code="FL", identifier="46")
        with mock_urlopen_serving({TITLE46_URL: SYNTHETIC_TITLE_HTML}):
            chapters = self.adapter.list_chapters(title_ref)

        assert [n.identifier for n in chapters] == ["1", "775", "782"]
        assert [n.name for n in chapters] == [
            "CONSTRUCTION OF STATUTES",
            "GENERAL PENALTIES; REGISTRATION OF CRIMINALS",
            "HOMICIDE",
        ]
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)
        assert all(n.ref.title == title_ref for n in chapters)

    def test_list_chapters_404_raises_ref_not_found(self) -> None:
        title_ref = TitleRef(state_code="FL", identifier="999")
        url = "https://www.flsenate.gov/Laws/Statutes/2025/Title999"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_chapters(title_ref)

    def test_list_chapters_network_failure_raises(self) -> None:
        title_ref = TitleRef(state_code="FL", identifier="46")
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(title_ref)

    def test_list_sections_real_fixture(self) -> None:
        chapter_ref = ChapterRef(
            title=TitleRef(state_code="FL", identifier="46"), identifier="775"
        )
        with mock_urlopen_serving({C775_ALL_URL: REAL_ALL_HTML}):
            sections = self.adapter.list_sections(chapter_ref)

        assert [n.identifier for n in sections] == ["775.01", "775.021", "775.15"]
        assert [n.name for n in sections] == [
            "Common law of England.",
            "Rules of construction.",
            "Time limitations; general time limitations; exceptions.",
        ]
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == chapter_ref for n in sections)

    def test_list_sections_404_raises_ref_not_found(self) -> None:
        chapter_ref = ChapterRef(
            title=TitleRef(state_code="FL", identifier="46"), identifier="999"
        )
        url = "https://www.flsenate.gov/Laws/Statutes/2025/Chapter999/All"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_sections(chapter_ref)

    def test_list_sections_no_blocks_raises(self) -> None:
        chapter_ref = ChapterRef(
            title=TitleRef(state_code="FL", identifier="46"), identifier="775"
        )
        with mock_urlopen_serving({C775_ALL_URL: "<html><body>no sections</body></html>"}):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_sections(chapter_ref)


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = FloridaAdapter()

    def test_simple_section_full_retrieval(self) -> None:
        ref = _make_ref("775.01")
        with mock_urlopen_serving({C775_ALL_URL: REAL_ALL_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "s. 775.01, Fla. Stat."
        assert section.citation.state_code == "FL"
        assert section.ref == ref
        assert section.heading == "Common law of England."
        assert section.text == (
            "The common law of England in relation to crimes, except so far as "
            "the same relates to the modes and degrees of punishment, shall be "
            "of full force in this state where there is no existing provision "
            "by statute on the subject."
        )
        assert section.amendment_notes == (
            "s. 1, Nov. 6, 1829; s. 1, Feb. 10, 1832; RS 2369; GS 3194; "
            "RGS 5024; CGL 7126."
        )
        assert section.status.value == "unknown"
        assert section.source_url == C775_ALL_URL
        assert section.retrieved_at is not None

    def test_multi_subsection_section(self) -> None:
        ref = _make_ref("775.021")
        with mock_urlopen_serving({C775_ALL_URL: REAL_ALL_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.heading == "Rules of construction."
        paragraphs = section.text.split("\n\n")
        # (1) (2) (3) (4)(a)(b)... and (5)(a)-(e) produce many paragraph blocks.
        assert len(paragraphs) >= 15
        assert paragraphs[0].startswith(
            "(1) The provisions of this code and offenses defined by other "
            "statutes shall be strictly construed"
        )
        assert "(4)(a) Whoever, in the course of one criminal transaction" in section.text
        assert "1. Offenses which require identical elements of proof." in section.text
        assert section.amendment_notes == (
            "s. 3, ch. 74-383; s. 1, ch. 76-66; s. 1, ch. 77-174; s. 1, "
            "ch. 83-156; s. 7, ch. 88-131; s. 2, ch. 2014-194."
        )

    def test_section_with_editorial_note(self) -> None:
        ref = _make_ref("775.15")
        with mock_urlopen_serving({C775_ALL_URL: REAL_ALL_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.heading.startswith("Time limitations; general time limitations")
        assert section.amendment_notes.endswith(
            "s. 6, ch. 2024-132; s. 2, ch. 2025-84.\n"
            "Note. — Former ss. 932.05, 932.06, 915.03, 932.465."
        )

    def test_section_boundaries_do_not_bleed(self) -> None:
        # 775.01 (first block) must not contain any text from 775.021
        # (the following block), and 775.15 (last block) must not bleed into
        # the fixture footer.
        ref = _make_ref("775.01")
        with mock_urlopen_serving({C775_ALL_URL: REAL_ALL_HTML}):
            section = self.adapter.retrieve_section(ref)
        assert "strictly construed" not in section.text
        assert "Time limitations" not in section.text

    def test_missing_anchor_raises_ref_not_found(self) -> None:
        ref = _make_ref("775.999")
        with mock_urlopen_serving({C775_ALL_URL: REAL_ALL_HTML}):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(ref)

    def test_chapter_404_raises_ref_not_found(self) -> None:
        ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="FL", identifier="46"),
                identifier="999",
            ),
            identifier="775.01",
        )
        url = "https://www.flsenate.gov/Laws/Statutes/2025/Chapter999/All"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable_error(self) -> None:
        ref = _make_ref("775.01")
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestParseEdgeCases:
    def setup_method(self) -> None:
        self.adapter = FloridaAdapter()

    def test_empty_body_raises_normalization_error(self) -> None:
        ref = _make_ref("775.01")
        html = (
            '<div class="Section"><span class="SectionNumber">775.01&#x2003;</span>'
            '<span class="Catchline"><span class="CatchlineText">Empty.</span></span>'
            '<span class="SectionBody">   \n </span>'
            '<div class="History"><span class="HistoryTitle">History.</span>'
            '<span class="HistoryText">s. 1, ch. 71-1.</span></div></div>'
        )
        with mock_urlopen_serving({C775_ALL_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)

    def test_missing_section_body_raises_normalization_error(self) -> None:
        ref = _make_ref("775.01")
        html = (
            '<div class="Section"><span class="SectionNumber">775.01&#x2003;</span>'
            '<span class="Catchline"><span class="CatchlineText">No body.</span></span>'
            '<div class="History"><span class="HistoryTitle">History.</span>'
            '<span class="HistoryText">s. 1, ch. 71-1.</span></div></div>'
        )
        with mock_urlopen_serving({C775_ALL_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)

    def test_block_without_section_number_raises_normalization_error(self) -> None:
        # A located block whose number disagrees with the request is a
        # structural change and must be signaled, not silently accepted.
        url = "https://www.flsenate.gov/Laws/Statutes/2025/Chapter775/All"
        block = (
            '<div class="Section"><span class="SectionNumber">775.02&#x2003;</span>'
            '<span class="Catchline"><span class="CatchlineText">Wrong.</span></span>'
            '<span class="SectionBody">Some body text.</span></div>'
        )
        with pytest.raises(NormalizationError):
            self.adapter._parse_section_block(
                block, "775.01", document_url=url
            )


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = FloridaAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("775.01")
        parsed = ParsedDocument(
            raw_citation="s. 775.01, Fla. Stat.",
            heading="Common law of England.",
            text="The common law of England ...",
            amendment_notes="s. 1, Nov. 6, 1829; RS 2369; CGL 7126.",
            source_url=C775_ALL_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "s. 775.01, Fla. Stat."
        assert section.citation.state_code == "FL"
        assert section.heading == "Common law of England."
        assert section.text == "The common law of England ..."
        assert section.amendment_notes == "s. 1, Nov. 6, 1829; RS 2369; CGL 7126."
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
            raw_citation="s. 775.01, Fla. Stat.",
            text="Some text.",
        )
        with pytest.raises(NormalizationError):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("775.01")
        parsed = ParsedDocument(
            raw_citation="s. 775.02, Fla. Stat.",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError):
            self.adapter.normalize(parsed, ref)
