"""Tests for HawaiiAdapter.

The Hawaii Revised Statutes (data.capitol.hawaii.gov) is a per-section HTML
source of Microsoft-Word-exported pages. The HRS maps directly onto the
framework's three-level ref model as Volume -> Chapter -> Section, with no
synthetic hierarchy. ``TitleRef.identifier`` is the volume number ("1"..
"14"); ``ChapterRef.identifier`` is the chapter number ("377", "1B");
``SectionRef.identifier`` is the full ``{chapter}-{section}`` citation
(e.g. "377-4.5", "1B-1"). History is the inline bracketed citation at the
end of the operative text; annotations (Attorney General Opinions, Law
Journals and Reviews, Case Notes, Cross References) are excluded; a
repealed section (e.g. 701-119) is returned with heading "REPEALED.",
empty text, the repeal citation in amendment_notes, and status REPEALED.

**REAL live fixtures**: the ``hi_*`` fixtures are verbatim captures of the
official host retrieved Aug 17 2026 (see ``docs/research/hawaii.md`` for
the proxy-based retrieval provenance); they are NOT synthetic. All tests
are fully offline: the real network boundary
(``urllib.request.urlopen``) is mocked, never adapter internals.
"""

from __future__ import annotations

import io
import urllib.error
from pathlib import Path

import pytest

from _mock_network import mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.hawaii.adapter import HawaiiAdapter
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

# --- REAL live fixtures: verbatim captures of the official host
# --- (data.capitol.hawaii.gov, fetched Aug 17 2026 via the r.jina.ai
# --- fetch proxy; see docs/research/hawaii.md).
FIXTURES = Path(__file__).parent / "fixtures"

HRSALL_HTML = (FIXTURES / "hi_hrsall.html").read_text(encoding="utf-8")
VOL1_CHAPTERS_HTML = (FIXTURES / "hi_vol01_chapters.html").read_text(
    encoding="utf-8"
)
VOL7_CHAPTERS_HTML = (FIXTURES / "hi_vol07_chapters.html").read_text(
    encoding="utf-8"
)
CH1_HTML = (FIXTURES / "hi_chapter_0001.html").read_text(encoding="utf-8")
CH1B_HTML = (FIXTURES / "hi_chapter_0001b.html").read_text(encoding="utf-8")
CH2_HTML = (FIXTURES / "hi_chapter_0002.html").read_text(encoding="utf-8")
CH377_HTML = (FIXTURES / "hi_chapter_0377.html").read_text(encoding="utf-8")
SEC1_1_HTML = (FIXTURES / "hi_section_1-1.html").read_text(encoding="utf-8")
SEC1_2_HTML = (FIXTURES / "hi_section_1-2.html").read_text(encoding="utf-8")
SEC1_4_5_HTML = (FIXTURES / "hi_section_1-4.5.html").read_text(encoding="utf-8")
SEC1_13_5_HTML = (FIXTURES / "hi_section_1-13.5.html").read_text(encoding="utf-8")
SEC1B_1_HTML = (FIXTURES / "hi_section_1b-1.html").read_text(encoding="utf-8")
SEC377_4_5_HTML = (FIXTURES / "hi_section_377-4.5.html").read_text(encoding="utf-8")
SEC701_119_HTML = (FIXTURES / "hi_section_701-119.html").read_text(encoding="utf-8")
NOT_FOUND_HTML = (FIXTURES / "hi_missing_chapter_404.html").read_bytes()

BASE = "https://data.capitol.hawaii.gov"

HRSALL_URL = f"{BASE}/hrsall"
VOL1_URL = f"{BASE}/hrsall/ChaptersByVolume.aspx?id=1"
VOL7_URL = f"{BASE}/hrsall/ChaptersByVolume.aspx?id=7"
CH1_URL = f"{BASE}/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-.htm"
CH1B_URL = f"{BASE}/hrscurrent/Vol01_Ch0001-0042F/HRS0001B/HRS_0001B-.htm"
CH2_URL = f"{BASE}/hrscurrent/Vol01_Ch0001-0042F/HRS0002/HRS_0002-.htm"
CH377_URL = f"{BASE}/hrscurrent/Vol07_Ch0346-0398/HRS0377/HRS_0377-.htm"
SEC1_1_URL = f"{BASE}/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0001.htm"
SEC1_2_URL = f"{BASE}/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0002.htm"
SEC1_4_5_URL = f"{BASE}/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0004_0005.htm"
SEC1_13_5_URL = f"{BASE}/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0013_0005.htm"
SEC1B_1_URL = f"{BASE}/hrscurrent/Vol01_Ch0001-0042F/HRS0001B/HRS_0001B-0001.htm"
SEC377_4_5_URL = (
    f"{BASE}/hrscurrent/Vol07_Ch0346-0398/HRS0377/HRS_0377-0004_0005.htm"
)
SEC701_119_URL = (
    f"{BASE}/hrscurrent/Vol14_Ch0701-0853/HRS0701/HRS_0701-0119.htm"
)
MISSING_CH_URL = (
    f"{BASE}/hrscurrent/Vol01_Ch0001-0042F/HRS0031/HRS_0031-.htm"
)


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the adapter's fetch wrapper
    will map to ``RefNotFoundError`` (404)."""
    return urllib.error.HTTPError(
        url, code, "Not Found", {}, io.BytesIO(NOT_FOUND_HTML)
    )


def _title_ref(identifier: str = "1") -> TitleRef:
    return TitleRef(state_code="HI", identifier=identifier)


def _chapter_ref(title: str = "1", chapter: str = "1") -> ChapterRef:
    return ChapterRef(title=_title_ref(title), identifier=chapter)


def _make_ref(section: str, volume: str) -> SectionRef:
    chapter = section.split("-", 1)[0]
    return SectionRef(
        chapter=_chapter_ref(title=volume, chapter=chapter),
        identifier=section,
    )


def _serve_all() -> dict[str, str]:
    return {
        HRSALL_URL: HRSALL_HTML,
        VOL1_URL: VOL1_CHAPTERS_HTML,
        VOL7_URL: VOL7_CHAPTERS_HTML,
        CH1_URL: CH1_HTML,
        CH1B_URL: CH1B_HTML,
        CH2_URL: CH2_HTML,
        CH377_URL: CH377_HTML,
        SEC1_1_URL: SEC1_1_HTML,
        SEC1_2_URL: SEC1_2_HTML,
        SEC1_4_5_URL: SEC1_4_5_HTML,
        SEC1_13_5_URL: SEC1_13_5_HTML,
        SEC1B_1_URL: SEC1B_1_HTML,
        SEC377_4_5_URL: SEC377_4_5_HTML,
        SEC701_119_URL: SEC701_119_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert HawaiiAdapter.__abstractmethods__ == frozenset()
        adapter = HawaiiAdapter()
        assert adapter.state_code == "HI"
        assert adapter.state_name == "Hawaii"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = HawaiiAdapter()

    def test_title_ref_url(self) -> None:
        assert self.adapter.build_url(_title_ref("1")) == VOL1_URL
        assert self.adapter.build_url(_title_ref("7")) == VOL7_URL

    def test_chapter_ref_url(self) -> None:
        assert self.adapter.build_url(_chapter_ref(title="1", chapter="1")) == CH1_URL
        assert self.adapter.build_url(_chapter_ref(title="1", chapter="1B")) == CH1B_URL
        assert self.adapter.build_url(_chapter_ref(title="7", chapter="377")) == CH377_URL

    def test_section_ref_url_plain(self) -> None:
        assert self.adapter.build_url(_make_ref("1-1", "1")) == SEC1_1_URL

    def test_section_ref_url_decimal(self) -> None:
        # VERIFIED filename mapping: "377-4.5" -> HRS_0377-0004_0005.htm,
        # "1-4.5" -> HRS_0001-0004_0005.htm, "1-13.5" -> HRS_0001-0013_0005.htm.
        assert self.adapter.build_url(_make_ref("377-4.5", "7")) == SEC377_4_5_URL
        assert self.adapter.build_url(_make_ref("1-4.5", "1")) == SEC1_4_5_URL
        assert self.adapter.build_url(_make_ref("1-13.5", "1")) == SEC1_13_5_URL

    def test_section_ref_url_lettered_chapter(self) -> None:
        # VERIFIED filename mapping: "1B-1" -> HRS_0001B-0001.htm.
        assert self.adapter.build_url(_make_ref("1B-1", "1")) == SEC1B_1_URL

    def test_section_ref_url_high_number(self) -> None:
        assert self.adapter.build_url(_make_ref("701-119", "14")) == SEC701_119_URL

    def test_unsupported_ref_for_unknown_volume(self) -> None:
        with pytest.raises(UnsupportedRefError, match="unknown HRS volume"):
            self.adapter.build_url(_title_ref("15"))
        with pytest.raises(UnsupportedRefError, match="unknown HRS volume"):
            self.adapter.build_url(_chapter_ref(title="0", chapter="1"))

    def test_unsupported_ref_for_malformed_section(self) -> None:
        ref = SectionRef(chapter=_chapter_ref(title="1", chapter="1"), identifier="foo")
        with pytest.raises(UnsupportedRefError, match="cannot address section"):
            self.adapter.build_url(ref)

    def test_unsupported_ref_for_chapter_mismatch(self) -> None:
        ref = SectionRef(
            chapter=_chapter_ref(title="7", chapter="377"),
            identifier="1B-1",
        )
        with pytest.raises(UnsupportedRefError, match="does not match"):
            self.adapter.build_url(ref)

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def test_returns_all_14_volumes(self) -> None:
        adapter = HawaiiAdapter()
        with mock_urlopen_serving({HRSALL_URL: HRSALL_HTML}):
            titles = adapter.list_titles()

        assert [t.identifier for t in titles] == [str(n) for n in range(1, 15)]
        assert titles[0].name == "VOLUME 1"
        assert titles[6].name == "VOLUME 7"
        assert all(t.level == HierarchyLevel.TITLE for t in titles)
        assert all(t.ref.state_code == "HI" for t in titles)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = HawaiiAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_titles()

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = HawaiiAdapter()
        with mock_urlopen_serving({HRSALL_URL: "<html><body>none</body></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable volume"):
                adapter.list_titles()


class TestListChapters:
    def test_returns_chapters_skipping_repealed(self) -> None:
        adapter = HawaiiAdapter()
        with mock_urlopen_serving({VOL1_URL: VOL1_CHAPTERS_HTML}):
            chapters = adapter.list_chapters(_title_ref("1"))

        # Volume 1 lists 68 chapter rows of which 10 are repealed; the
        # adapter skips those, and the lettered chapters are preserved.
        assert len(chapters) == 58
        assert chapters[0].identifier == "1"
        assert chapters[0].name == "COMMON LAW; CONSTRUCTION OF LAWS"
        assert any(c.identifier == "1B" for c in chapters)
        assert all(c.identifier != "2" for c in chapters)  # repealed
        assert all("REPEALED" not in c.name.upper() for c in chapters)
        assert all(c.level == HierarchyLevel.CHAPTER for c in chapters)
        assert all(c.ref.title == _title_ref("1") for c in chapters)

    def test_lettered_chapters_kept(self) -> None:
        adapter = HawaiiAdapter()
        with mock_urlopen_serving({VOL7_URL: VOL7_CHAPTERS_HTML}):
            chapters = adapter.list_chapters(_title_ref("7"))
        assert any(c.identifier == "377" for c in chapters)
        assert any(c.identifier == "346C" for c in chapters)

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = HawaiiAdapter()
        with mock_urlopen_error(_http_error(VOL1_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_chapters(_title_ref("1"))

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = HawaiiAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_chapters(_title_ref("1"))

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = HawaiiAdapter()
        with mock_urlopen_serving({VOL1_URL: "<html></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable chapter"):
                adapter.list_chapters(_title_ref("1"))


class TestListSections:
    def test_returns_sections_from_chapter_page(self) -> None:
        adapter = HawaiiAdapter()
        with mock_urlopen_serving({CH377_URL: CH377_HTML}):
            sections = adapter.list_sections(_chapter_ref(title="7", chapter="377"))

        ids = [s.identifier for s in sections]
        assert "377-1" in ids and "377-18" in ids
        assert "377-4.5" in ids  # decimal section
        assert len(ids) == len(set(ids))
        decimal = next(s for s in sections if s.identifier == "377-4.5")
        assert decimal.name == "Religious exemption from labor organization membership"
        assert all(s.level == HierarchyLevel.SECTION for s in sections)
        assert all(
            s.ref.chapter == _chapter_ref(title="7", chapter="377") for s in sections
        )

    def test_title_page_returns_chapter_one_sections(self) -> None:
        # Chapter 1's page is the printed title page; its chapter rows
        # ("1 Common Law; Construction of Laws") must not leak in.
        adapter = HawaiiAdapter()
        with mock_urlopen_serving({CH1_URL: CH1_HTML}):
            sections = adapter.list_sections(_chapter_ref(title="1", chapter="1"))

        ids = [s.identifier for s in sections]
        assert ids[0] == "1-1"
        assert "1-13.5" in ids
        assert "1-32" in ids
        assert all(s.identifier.startswith("1-") for s in sections)

    def test_repealed_chapter_has_no_sections(self) -> None:
        adapter = HawaiiAdapter()
        with mock_urlopen_serving({CH2_URL: CH2_HTML}):
            with pytest.raises(AdapterUnavailableError, match="no usable section"):
                adapter.list_sections(_chapter_ref(title="1", chapter="2"))

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = HawaiiAdapter()
        with mock_urlopen_error(_http_error(CH377_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_sections(_chapter_ref(title="7", chapter="377"))

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = HawaiiAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_sections(_chapter_ref(title="7", chapter="377"))


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = HawaiiAdapter()

    def test_full_retrieval_older_chapter(self) -> None:
        # Section 1-1: older chapter, single body paragraph, AG Opinions
        # annotations that must be excluded, inline bracketed history.
        ref = _make_ref("1-1", "1")
        with mock_urlopen_serving({SEC1_1_URL: SEC1_1_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Haw. Rev. Stat. Section 1-1"
        assert section.citation.state_code == "HI"
        assert section.ref == ref
        assert section.heading == "Common law of the State; exceptions."
        assert section.text.startswith(
            "The common law of England, as ascertained by English and American "
            "decisions, is declared to be the common law of the State of Hawaii "
            "in all cases"
        )
        assert "Attorney General Opinions" not in section.text
        assert "Att. Gen. Op. 92-4" not in section.text
        assert section.amendment_notes == (
            "[L 1892, c 57, §5; am L 1903, c 32, §2; RL 1925, §1; RL 1935, §1; "
            "RL 1945, §1; RL 1955, §1-1; HRS §1-1]"
        )
        assert section.status.value == "unknown"
        assert section.source_url == SEC1_1_URL
        assert section.retrieved_at is not None

    def test_split_bold_heading_section(self) -> None:
        # Section 1-2: the heading is split across bold runs
        # ("<b>§1</b>-<b>2 ...</b>") which cleans to "§1 - 2 ..."; the citation
        # must still cross-check against "1-2" and the heading must be clean.
        ref = _make_ref("1-2", "1")
        with mock_urlopen_serving({SEC1_2_URL: SEC1_2_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.heading == "Certain laws not obligatory until published."
        assert section.text.startswith(
            "No written law, unless otherwise specifically provided"
        )
        assert "Case Notes" not in section.text
        assert section.amendment_notes.startswith("[CC 1859, §1; RL 1925, §3;")

    def test_decimal_section(self) -> None:
        # Section 1-4.5: decimal citation wrapped in brackets "[§1-4.5]".
        ref = _make_ref("1-4.5", "1")
        with mock_urlopen_serving({SEC1_4_5_URL: SEC1_4_5_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.heading == "Cession of concurrent jurisdiction."
        assert section.text.startswith("(a)")
        assert section.amendment_notes == "[L 1998, c 291, §1]"

    def test_multi_paragraph_body_excludes_annotations(self) -> None:
        # Section 1-13.5: (a)-(g) body paragraphs plus (1)-(6) oneParagraph
        # items; Law Journals and Reviews annotations must be excluded.
        ref = _make_ref("1-13.5", "1")
        with mock_urlopen_serving({SEC1_13_5_URL: SEC1_13_5_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.heading == "Hawaiian language; spelling."
        assert section.text.startswith("(a) Kahakō and `okina may be used")
        assert "(g) For the purpose of this section" in section.text
        assert '"Hawaiian Dictionary: Hawaiian-English, English-Hawaiian"' in (
            section.text
        )
        assert "Law Journals and Reviews" not in section.text
        assert "30 UH L. Rev. 243" not in section.text
        assert section.amendment_notes == "[L 1992, c 169, §2; am L 2022, c 170, §2]"

    def test_lettered_chapter_section(self) -> None:
        # Section 1B-1: chapter 1B, bracketed citation, and no history bracket
        # at all -> amendment_notes stays None.
        ref = _make_ref("1B-1", "1")
        with mock_urlopen_serving({SEC1B_1_URL: SEC1B_1_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.heading == "Rural areas and federal programs."
        assert section.text.startswith(
            '(a) The term "rural" under this section shall be strictly used'
        )
        assert "If an island's population density exceeds" in section.text
        assert section.amendment_notes == "[L 2013, c 144, §2]"
        assert section.status.value == "unknown"

    def test_repealed_section(self) -> None:
        # VERIFIED: a repealed section (701-119) renders a "REPEALED." heading
        # with the repeal citation as the following text and Cross References
        # annotations. Per the structural-signal rule it is returned with
        # empty text, the repeal citation in amendment_notes, and status
        # REPEALED.
        ref = _make_ref("701-119", "14")
        with mock_urlopen_serving({SEC701_119_URL: SEC701_119_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Haw. Rev. Stat. Section 701-119"
        assert section.heading == "REPEALED."
        assert section.text == ""
        assert section.amendment_notes == (
            "L 1988, c 260, §§4, 7; L 1996, c 104, §6."
        )
        assert section.status.value == "repealed"
        assert "Cross References" not in section.text
        assert "Forfeiture of property" not in section.text

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        # The page's own heading citation must equal ref.identifier. Doctored
        # surgically: the heading's section number is rewritten.
        html = SEC377_4_5_HTML.replace("§377-4.5", "§377-4.6", 1)
        with mock_urlopen_serving({SEC377_4_5_URL: html}):
            with pytest.raises(RefMismatchError, match="does not match"):
                self.adapter.retrieve_section(_make_ref("377-4.5", "7"))

    def test_no_word_section_raises_normalization_error(self) -> None:
        html = "<html><body><p>nothing here</p></body></html>"
        with mock_urlopen_serving({SEC1_1_URL: html}):
            with pytest.raises(NormalizationError, match="WordSection1"):
                self.adapter.retrieve_section(_make_ref("1-1", "1"))

    def test_no_heading_element_raises_normalization_error(self) -> None:
        html = (
            "<html><body><div class=\"WordSection1\">"
            "<p class=\"RegularParagraphs\">Plain text without bold.</p>"
            "</div></body></html>"
        )
        with mock_urlopen_serving({SEC1_1_URL: html}):
            with pytest.raises(NormalizationError, match="no heading"):
                self.adapter.retrieve_section(_make_ref("1-1", "1"))

    def test_no_citation_in_heading_raises_normalization_error(self) -> None:
        html = (
            "<html><body><div class=\"WordSection1\">"
            "<p class=\"RegularParagraphs\"><b>Some title without a citation.</b></p>"
            "</div></body></html>"
        )
        with mock_urlopen_serving({SEC1_1_URL: html}):
            with pytest.raises(NormalizationError, match="no numbered citation"):
                self.adapter.retrieve_section(_make_ref("1-1", "1"))

    def test_empty_body_normal_section_raises_normalization_error(self) -> None:
        html = (
            "<html><body><div class=\"WordSection1\">"
            "<p class=\"RegularParagraphs\"><b>§1-1&#160; Heading only.</b></p>"
            "</div></body></html>"
        )
        with mock_urlopen_serving({SEC1_1_URL: html}):
            with pytest.raises(NormalizationError, match="empty after cleaning"):
                self.adapter.retrieve_section(_make_ref("1-1", "1"))

    def test_missing_section_404_maps_to_ref_not_found(self) -> None:
        # A deliberately nonexistent chapter (HRS0031) was reported by the
        # fetch proxy to return upstream HTTP 404 with the IIS 404 error
        # page; the mapping 404 -> RefNotFoundError is per project
        # convention (UNVERIFIED directly, see docs/research/hawaii.md).
        with mock_urlopen_error(_http_error(MISSING_CH_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                self.adapter.retrieve_section(_make_ref("31-1", "1"))

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        ref = _make_ref("1-1", "1")
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = HawaiiAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("377-4.5", "7")
        parsed = ParsedDocument(
            raw_citation="Haw. Rev. Stat. Section 377-4.5",
            heading="Religious exemption from labor organization membership.",
            text="Notwithstanding any other provision of law to the contrary...",
            amendment_notes="[L 1982, c 102, §2; am L 1983, c 124, §9]",
            source_url=SEC377_4_5_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "Haw. Rev. Stat. Section 377-4.5"
        assert section.citation.state_code == "HI"
        assert section.status.value == "unknown"

    def test_normalize_repealed_sets_status(self) -> None:
        ref = _make_ref("701-119", "14")
        parsed = ParsedDocument(
            raw_citation="Haw. Rev. Stat. Section 701-119",
            heading="REPEALED.",
            text="",
            amendment_notes="L 1988, c 260, §§4, 7; L 1996, c 104, §6.",
        )
        section = self.adapter.normalize(parsed, ref)
        assert section.status.value == "repealed"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(title=TitleRef(state_code="NV", identifier="1"), identifier="1"),
            identifier="1-1",
        )
        parsed = ParsedDocument(
            raw_citation="Haw. Rev. Stat. Section 1-1",
            text="Some text.",
        )
        with pytest.raises(NormalizationError, match="expected 'HI'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("1-1", "1")
        parsed = ParsedDocument(
            raw_citation="Haw. Rev. Stat. Section 1-2",
            text="Some text.",
        )
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)


class TestHierarchyMapping:
    def test_real_three_level_hierarchy(self) -> None:
        # Volume -> Chapter -> Section, no synthetic title.
        adapter = HawaiiAdapter()
        with mock_urlopen_serving(_serve_all()):
            titles = adapter.list_titles()
            title = next(t.ref for t in titles if t.identifier == "7")
            assert isinstance(title, TitleRef)
            assert title.state_code == "HI"

            chapters = adapter.list_chapters(title)
            assert all(c.ref.title == title for c in chapters)

            chapter = next(c.ref for c in chapters if c.identifier == "377")
            sections = adapter.list_sections(chapter)
            assert all(s.ref.chapter.title == title for s in sections)
            assert all(s.ref.chapter == chapter for s in sections)

            section_ref = next(s.ref for s in sections if s.identifier == "377-4.5")
            section = adapter.retrieve_section(section_ref)
            assert section.citation.raw == "Haw. Rev. Stat. Section 377-4.5"
            assert section.heading == (
                "Religious exemption from labor organization membership."
            )
