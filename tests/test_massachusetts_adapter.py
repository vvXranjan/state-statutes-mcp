"""Tests for MassachusettsAdapter.

The Massachusetts General Laws (malegislature.gov/Laws/GeneralLaws) is a
per-section HTML source (the Family A model) with a real Part -> Title ->
Chapter -> Section hierarchy that is folded into the framework's three-level
ref model entirely inside the adapter: ``TitleRef.identifier`` is the
``"Part {part} Title {title}"`` form (e.g. ``"Part I Title I"``), the Part
pages use a single GLOBAL titleId counter across all five Parts
(Part I: 1-22, II: 23-25, III: 26-31, IV: 32-33, V: 34), and the chapter
lists are lazy-loaded through an internal AJAX endpoint
(``GetChaptersForTitle?partId={n}&titleId={m}&code={roman}``).

``SectionRef.identifier`` is the section number as listed on the chapter
page (e.g. ``"7"``, ``"7A"``, ``"6 1/2"``, ``"160 to 168A"``) and the URL
encodes ``/`` as ``~`` before URL-quoting. There is no history/amendment
text on the section pages, so ``amendment_notes`` is always ``None``;
repealed/amended-into-a-special-act sections render only a prose caption
with an empty body and are returned with ``status=UNKNOWN``, the caption
as ``heading``, and ``text=""``.

**REAL proxy-captured fixtures**: the ``ma_*`` fixtures are verbatim slices
of the official malegislature.gov General Laws pages captured on Aug 20
2026 via the r.jina.ai proxy with ``X-Return-Format: html`` (malegislature.gov
does not accept direct sockets from this environment; see
``docs/research/massachusetts.md``). They are NOT synthetic.

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against these fixtures. All tests are fully offline:
the real network boundary (``urllib.request.urlopen``) is mocked, never
adapter internals.
"""

from __future__ import annotations

import io
import urllib.error
from pathlib import Path

import pytest

from _mock_network import mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.massachusetts.adapter import MassachusettsAdapter
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

# --- REAL proxy-captured fixtures: verbatim slices of the official host
# --- (malegislature.gov/Laws/GeneralLaws, fetched Aug 20 2026 via the
# --- r.jina.ai proxy; see docs/research/massachusetts.md).
FIXTURES = Path(__file__).parent / "fixtures"

GL_HTML = (FIXTURES / "ma_gl.html").read_text(encoding="utf-8")
PART_I_HTML = (FIXTURES / "ma_part_i.html").read_text(encoding="utf-8")
PART_II_HTML = (FIXTURES / "ma_part_ii.html").read_text(encoding="utf-8")
PART_III_HTML = (FIXTURES / "ma_part_iii.html").read_text(encoding="utf-8")
PART_IV_HTML = (FIXTURES / "ma_part_iv.html").read_text(encoding="utf-8")
PART_V_HTML = (FIXTURES / "ma_part_v.html").read_text(encoding="utf-8")
AJAX_TITLE_I_HTML = (FIXTURES / "ma_ajax_title_i.html").read_text(encoding="utf-8")
AJAX_TITLE_II_HTML = (FIXTURES / "ma_ajax_title_ii.html").read_text(encoding="utf-8")
CH4_HTML = (FIXTURES / "ma_ch4.html").read_text(encoding="utf-8")
CH149_HTML = (FIXTURES / "ma_ch149.html").read_text(encoding="utf-8")
CH186_HTML = (FIXTURES / "ma_ch186.html").read_text(encoding="utf-8")
CH6A_HTML = (FIXTURES / "ma_ch6a.html").read_text(encoding="utf-8")
SEC7_HTML = (FIXTURES / "ma_sec7.html").read_text(encoding="utf-8")
SEC7A_HTML = (FIXTURES / "ma_sec7a.html").read_text(encoding="utf-8")
SEC6_12_HTML = (FIXTURES / "ma_sec6_12.html").read_text(encoding="utf-8")
SEC160TO168A_HTML = (FIXTURES / "ma_sec160to168a.html").read_text(encoding="utf-8")
SEC186_1_HTML = (FIXTURES / "ma_sec186_1.html").read_text(encoding="utf-8")
NOT_FOUND_HTML = (FIXTURES / "ma_404.html").read_text(encoding="utf-8")

BASE = "https://malegislature.gov/Laws/GeneralLaws"

GL_URL = f"{BASE}"
PART_HTML_BY_NAME = {
    "I": PART_I_HTML,
    "II": PART_II_HTML,
    "III": PART_III_HTML,
    "IV": PART_IV_HTML,
    "V": PART_V_HTML,
}


def _part_page_served() -> dict[str, str]:
    """Map every Part page URL to its fixture HTML."""
    return {f"{BASE}/Part{name}": html for name, html in PART_HTML_BY_NAME.items()}


def _title_ref(identifier: str = "Part I Title I") -> TitleRef:
    return TitleRef(state_code="MA", identifier=identifier)


def _chapter_ref(
    title: str = "Part I Title I", chapter: str = "4"
) -> ChapterRef:
    return ChapterRef(title=_title_ref(title), identifier=chapter)


def _make_ref(
    title: str = "Part I Title I", chapter: str = "4", section: str = "7"
) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(title=title, chapter=chapter), identifier=section)


def _serve_all() -> dict[str, str]:
    """Serve every fixture used by the discovery + retrieval tests."""
    return {
        GL_URL: GL_HTML,
        **_part_page_served(),
        MassachusettsAdapter()._chapters_url(_title_ref("Part I Title I")): AJAX_TITLE_I_HTML,
        MassachusettsAdapter()._chapters_url(_title_ref("Part I Title II")): AJAX_TITLE_II_HTML,
        MassachusettsAdapter().build_url(_chapter_ref()): CH4_HTML,
        MassachusettsAdapter().build_url(_chapter_ref(title="Part II Title I", chapter="186")): CH186_HTML,
        MassachusettsAdapter().build_url(_chapter_ref(title="Part I Title XXI", chapter="149")): CH149_HTML,
        MassachusettsAdapter().build_url(_chapter_ref(title="Part I Title II", chapter="6A")): CH6A_HTML,
        MassachusettsAdapter().build_url(_make_ref()): SEC7_HTML,
        MassachusettsAdapter().build_url(_make_ref(section="7A")): SEC7A_HTML,
        MassachusettsAdapter().build_url(_make_ref(title="Part I Title XXI", chapter="149", section="6 1/2")): SEC6_12_HTML,
        MassachusettsAdapter().build_url(_make_ref(title="Part I Title XXI", chapter="149", section="160 to 168A")): SEC160TO168A_HTML,
        MassachusettsAdapter().build_url(_make_ref(title="Part II Title I", chapter="186", section="1")): SEC186_1_HTML,
    }


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the adapter's fetch wrapper
    will map to ``RefNotFoundError`` (404)."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert MassachusettsAdapter.__abstractmethods__ == frozenset()
        adapter = MassachusettsAdapter()
        assert adapter.state_code == "MA"
        assert adapter.state_name == "Massachusetts"


class TestTitleIdArithmetic:
    """Focused unit tests for the global titleId arithmetic that drives
    chapter listing -- the one genuinely novel piece of Massachusetts
    logic (global counter across all five Parts)."""

    def test_global_title_id_offsets(self) -> None:
        adapter = MassachusettsAdapter()
        # Part I: 1-22, Part II: 23-25, Part III: 26-31, Part IV: 32-33,
        # Part V: 34 (all VERIFIED from the live Part page captures).
        assert adapter._title_id("I", "I", what="t") == 1
        assert adapter._title_id("I", "XXII", what="t") == 22
        assert adapter._title_id("II", "I", what="t") == 23
        assert adapter._title_id("II", "III", what="t") == 25
        assert adapter._title_id("III", "I", what="t") == 26
        assert adapter._title_id("IV", "I", what="t") == 32
        assert adapter._title_id("V", "I", what="t") == 34

    def test_title_position_beyond_part_count_raises_ref_not_found(self) -> None:
        adapter = MassachusettsAdapter()
        with pytest.raises(RefNotFoundError, match="does not exist"):
            adapter._title_id("I", "XXIII", what="title listing")

    def test_nonexistent_part_raises_unsupported_ref(self) -> None:
        adapter = MassachusettsAdapter()
        # The chapter-listing path guards the part name before resolving the
        # titleId, so a Part outside I-V is rejected up front.
        title = _title_ref("Part VI Title I")
        with pytest.raises(UnsupportedRefError, match="not one of the five"):
            adapter._chapters_url(title)


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = MassachusettsAdapter()

    def test_section_ref_url(self) -> None:
        assert self.adapter.build_url(_make_ref()) == (
            f"{BASE}/PartI/TitleI/Chapter4/Section7"
        )

    def test_lettered_section_url(self) -> None:
        assert self.adapter.build_url(_make_ref(section="7A")) == (
            f"{BASE}/PartI/TitleI/Chapter4/Section7A"
        )

    def test_fractional_section_url(self) -> None:
        # "6 1/2" -> "/" encoded as "~" before URL-quoting (VERIFIED).
        assert self.adapter.build_url(
            _make_ref(title="Part I Title XXI", chapter="149", section="6 1/2")
        ) == f"{BASE}/PartI/TitleXXI/Chapter149/Section6%201~2"

    def test_repealed_range_section_url(self) -> None:
        assert self.adapter.build_url(
            _make_ref(title="Part I Title XXI", chapter="149", section="160 to 168A")
        ) == f"{BASE}/PartI/TitleXXI/Chapter149/Section160%20to%20168A"

    def test_chapter_ref_url(self) -> None:
        assert self.adapter.build_url(_chapter_ref()) == (
            f"{BASE}/PartI/TitleI/Chapter4"
        )

    def test_lettered_chapter_ref_url(self) -> None:
        assert self.adapter.build_url(
            _chapter_ref(title="Part I Title II", chapter="6A")
        ) == f"{BASE}/PartI/TitleII/Chapter6A"

    def test_title_ref_url_points_to_part_page(self) -> None:
        # A Massachusetts TitleRef resolves to the Part page (the closest
        # real document; chapter listing uses the AJAX endpoint instead).
        assert self.adapter.build_url(_title_ref("Part I Title I")) == (
            f"{BASE}/PartI"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]

    def test_malformed_title_identifier_raises_unsupported_ref(self) -> None:
        with pytest.raises(UnsupportedRefError, match="expected a"):
            self.adapter.build_url(_title_ref("not a title"))


class TestListTitles:
    def test_returns_all_34_titles_across_five_parts(self) -> None:
        adapter = MassachusettsAdapter()
        served = {GL_URL: GL_HTML, **_part_page_served()}
        with mock_urlopen_serving(served):
            titles = adapter.list_titles()

        # VERIFIED: Part I holds 22 titles, II 3, III 6, IV 2, V 1 = 34.
        assert len(titles) == 34
        assert all(t.level == HierarchyLevel.TITLE for t in titles)
        assert all(t.ref.state_code == "MA" for t in titles)
        assert titles[0].identifier == "Part I Title I"
        assert titles[0].name == (
            "JURISDICTION AND EMBLEMS OF THE COMMONWEALTH, THE GENERAL "
            "COURT, STATUTES AND PUBLIC DOCUMENTS"
        )
        assert titles[-1].identifier == "Part V Title I"
        assert titles[-1].name == (
            "THE GENERAL LAWS, AND EXPRESS REPEAL OF CERTAIN ACTS AND "
            "RESOLVES"
        )

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = MassachusettsAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_titles()

    def test_empty_index_raises_adapter_unavailable(self) -> None:
        adapter = MassachusettsAdapter()
        with mock_urlopen_serving({GL_URL: "<html><body>none</body></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable Part"):
                adapter.list_titles()


class TestListChapters:
    def test_returns_chapters_for_part_i_title_i(self) -> None:
        adapter = MassachusettsAdapter()
        title = _title_ref("Part I Title I")
        url = adapter._chapters_url(title)
        with mock_urlopen_serving({url: AJAX_TITLE_I_HTML}):
            chapters = adapter.list_chapters(title)

        assert [c.identifier for c in chapters] == ["1", "2", "3", "4", "5"]
        assert chapters[0].name == "JURISDICTION OF THE COMMONWEALTH AND OF THE UNITED STATES"
        assert chapters[-1].name.startswith("PRINTING AND DISTRIBUTION OF LAWS")
        assert all(c.level == HierarchyLevel.CHAPTER for c in chapters)
        assert all(c.ref.title == title for c in chapters)

    def test_lettered_chapter_included_in_title_ii(self) -> None:
        adapter = MassachusettsAdapter()
        title = _title_ref("Part I Title II")
        url = adapter._chapters_url(title)
        with mock_urlopen_serving({url: AJAX_TITLE_II_HTML}):
            chapters = adapter.list_chapters(title)

        assert "6A" in [c.identifier for c in chapters]
        ch6a = next(c for c in chapters if c.identifier == "6A")
        assert ch6a.name == "EXECUTIVE OFFICES"

    def test_out_of_range_title_raises_ref_not_found(self) -> None:
        adapter = MassachusettsAdapter()
        title = _title_ref("Part I Title XXIII")
        with pytest.raises(RefNotFoundError, match="does not exist"):
            adapter.list_chapters(title)

    def test_nonexistent_part_raises_unsupported_ref(self) -> None:
        adapter = MassachusettsAdapter()
        title = _title_ref("Part VI Title I")
        with pytest.raises(UnsupportedRefError, match="not one of the five"):
            adapter.list_chapters(title)

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = MassachusettsAdapter()
        title = _title_ref("Part I Title I")
        url = adapter._chapters_url(title)
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_chapters(title)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = MassachusettsAdapter()
        title = _title_ref("Part I Title I")
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_chapters(title)

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = MassachusettsAdapter()
        title = _title_ref("Part I Title I")
        url = adapter._chapters_url(title)
        with mock_urlopen_serving({url: "<html><body>none</body></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable chapter"):
                adapter.list_chapters(title)


class TestListSections:
    def test_returns_sections_for_chapter_4(self) -> None:
        adapter = MassachusettsAdapter()
        chapter = _chapter_ref()
        url = adapter.build_url(chapter)
        with mock_urlopen_serving({url: CH4_HTML}):
            sections = adapter.list_sections(chapter)

        ids = [s.identifier for s in sections]
        assert "1" in ids and "7" in ids and "7A" in ids and "9A" in ids
        assert len(ids) == len(set(ids))
        sec7 = next(s for s in sections if s.identifier == "7")
        assert sec7.name == "Definitions of statutory terms; statutory construction"
        assert all(s.level == HierarchyLevel.SECTION for s in sections)
        assert all(s.ref.chapter == chapter for s in sections)

    def test_repealed_section_rows_listed_with_prose_names(self) -> None:
        # VERIFIED: repealed individual sections and repealed ranges are
        # ordinary TOC rows (no filtering), e.g. Section 1 of ch. 186 is
        # listed with the name "Repealed, 2008, 521, Sec. 5".
        adapter = MassachusettsAdapter()
        chapter = _chapter_ref(title="Part II Title I", chapter="186")
        url = adapter.build_url(chapter)
        with mock_urlopen_serving({url: CH186_HTML}):
            sections = adapter.list_sections(chapter)

        sec1 = next(s for s in sections if s.identifier == "1")
        assert sec1.name == "Repealed, 2008, 521, Sec. 5"

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = MassachusettsAdapter()
        chapter = _chapter_ref()
        url = adapter.build_url(chapter)
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_sections(chapter)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = MassachusettsAdapter()
        chapter = _chapter_ref()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_sections(chapter)

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = MassachusettsAdapter()
        chapter = _chapter_ref()
        url = adapter.build_url(chapter)
        with mock_urlopen_serving({url: "<html><body>none</body></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable section"):
                adapter.list_sections(chapter)


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = MassachusettsAdapter()

    def test_full_retrieval_normal_section(self) -> None:
        ref = _make_ref()
        url = self.adapter.build_url(ref)
        with mock_urlopen_serving({url: SEC7_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "G.L. c. 4, § 7"
        assert section.citation.state_code == "MA"
        assert section.ref == ref
        assert section.heading == (
            "Definitions of statutory terms; statutory construction"
        )
        assert section.text.startswith(
            "Section 7. In construing statutes the following words"
        )
        assert "First, \"Aldermen''" in section.text
        assert section.status.value == "unknown"
        assert section.amendment_notes is None
        assert section.source_url == url
        assert section.retrieved_at is not None

    def test_lettered_section_retrieval(self) -> None:
        ref = _make_ref(section="7A")
        url = self.adapter.build_url(ref)
        with mock_urlopen_serving({url: SEC7A_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "G.L. c. 4, § 7A"
        # 7A was amended into a special act: prose caption, empty body,
        # status UNKNOWN (no structural repeal signal, same rule as
        # NebraskaAdapter).
        assert section.heading == "Amended by 1931, 394, Sec. 182 into a special act"
        assert section.text == ""
        assert section.status.value == "unknown"
        assert section.amendment_notes is None

    def test_fractional_section_retrieval(self) -> None:
        ref = _make_ref(title="Part I Title XXI", chapter="149", section="6 1/2")
        url = self.adapter.build_url(ref)
        with mock_urlopen_serving({url: SEC6_12_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "G.L. c. 149, § 6 1/2"
        assert section.heading == (
            "Protection of employees consistent with federal Occupational "
            "Safety and Health Act; occupational health and safety hazard "
            "advisory board"
        )
        assert section.text.startswith("Section 6 1/2. (a) For the purposes")

    def test_repealed_range_section_retrieval(self) -> None:
        ref = _make_ref(title="Part I Title XXI", chapter="149", section="160 to 168A")
        url = self.adapter.build_url(ref)
        with mock_urlopen_serving({url: SEC160TO168A_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "G.L. c. 149, § 160 to 168A"
        assert section.heading == "Repealed, 2011, 3, Sec. 131"
        assert section.text == ""
        assert section.status.value == "unknown"
        assert section.amendment_notes is None

    def test_repealed_section_retrieval(self) -> None:
        ref = _make_ref(title="Part II Title I", chapter="186", section="1")
        url = self.adapter.build_url(ref)
        with mock_urlopen_serving({url: SEC186_1_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "G.L. c. 186, § 1"
        assert section.heading == "Repealed, 2008, 521, Sec. 5"
        assert section.text == ""
        assert section.status.value == "unknown"

    def test_soft_404_maps_to_ref_not_found(self) -> None:
        # VERIFIED: a nonexistent section returns HTTP 200 whose body
        # contains "404 - Page Not Found"; the adapter detects the marker.
        ref = _make_ref(section="7A")
        url = self.adapter.build_url(ref)
        with mock_urlopen_serving({url: NOT_FOUND_HTML}):
            with pytest.raises(RefNotFoundError, match="did not resolve"):
                self.adapter.retrieve_section(ref)

    def test_real_404_maps_to_ref_not_found(self) -> None:
        ref = _make_ref()
        url = self.adapter.build_url(ref)
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        ref = _make_ref()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)

    def test_missing_heading_raises_normalization_error(self) -> None:
        ref = _make_ref()
        url = self.adapter.build_url(ref)
        with mock_urlopen_serving({url: "<html><body><p>nothing</p></body></html>"}):
            with pytest.raises(NormalizationError, match="no genLawHeading"):
                self.adapter.retrieve_section(ref)

    def test_section_identifier_mismatch_raises_ref_mismatch_error(self) -> None:
        # The page's own heading identifier must equal ref.identifier.
        # Doctored surgically: the operative heading caption is rewritten,
        # leaving the nav/breadcrumb occurrences alone.
        html = SEC7_HTML.replace("Section 7:", "Section 9:", 1)
        ref = _make_ref()
        url = self.adapter.build_url(ref)
        with mock_urlopen_serving({url: html}):
            with pytest.raises(RefMismatchError, match="does not match"):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = MassachusettsAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref()
        parsed = ParsedDocument(
            raw_citation="G.L. c. 4, § 7",
            heading="Definitions of statutory terms; statutory construction",
            text="Section 7. In construing statutes ...",
            amendment_notes=None,
            source_url=self.adapter.build_url(ref),
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "G.L. c. 4, § 7"
        assert section.citation.state_code == "MA"
        assert section.heading == "Definitions of statutory terms; statutory construction"
        assert section.status.value == "unknown"
        assert section.amendment_notes is None

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="NV", identifier="x"),
                identifier="4",
            ),
            identifier="7",
        )
        parsed = ParsedDocument(
            raw_citation="G.L. c. 4, § 7",
            text="Some text.",
        )
        with pytest.raises(NormalizationError, match="expected 'MA'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref()
        parsed = ParsedDocument(
            raw_citation="G.L. c. 4, § 9",
            text="Some text.",
        )
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)


class TestHierarchyMapping:
    def test_part_title_chapter_section_chain_descends(self) -> None:
        # The real 4-level hierarchy (Part -> Title -> Chapter -> Section)
        # is folded into the 3-level ref model entirely inside the adapter.
        adapter = MassachusettsAdapter()
        with mock_urlopen_serving(_serve_all()):
            titles = adapter.list_titles()
            title = next(t.ref for t in titles if t.identifier == "Part I Title I")
            assert isinstance(title, TitleRef)
            assert title.state_code == "MA"
            assert title.identifier == "Part I Title I"

            chapters = adapter.list_chapters(title)
            assert all(c.ref.title == title for c in chapters)
            chapter = next(c.ref for c in chapters if c.identifier == "4")
            assert isinstance(chapter, ChapterRef)
            assert chapter.title == title

            sections = adapter.list_sections(chapter)
            assert all(s.ref.chapter.title == title for s in sections)
            assert all(s.ref.chapter == chapter for s in sections)

            section = next(s.ref for s in sections if s.identifier == "7")
            retrieved = adapter.retrieve_section(section)
            assert retrieved.citation.raw == "G.L. c. 4, § 7"
            assert retrieved.text.startswith("Section 7.")