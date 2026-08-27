"""Tests for CaliforniaAdapter.

The California Codes (leginfo.legislature.ca.gov) are served as
server-rendered HTML over ordinary HTTP GETs -- no JS, no forms, no browser
automation, and no bulk archive. The fixtures used here are REAL official
live captures of the official host taken Aug 27 2026 from this environment
(see docs/research/california.md); only the JSF ``javax.faces.ViewState``
hidden-field value has been stubbed to reduce size -- the statute HTML is
preserved verbatim.

Hierarchy mapping: TitleRef = Code (e.g. "BPC"); ChapterRef = one fetchable
statute document identified by its ``division/part/chapter/article``
segments (e.g. "3//1/1" for Division 3, Chapter 1, Article 1; "///" for the
General Provisions); SectionRef.identifier = the section number (e.g.
"5000", "5025.3").

Network tests mock the real network boundary
(``urllib.request.urlopen`` as imported by the shared ``_fetch`` helper),
never adapter internals.
"""

from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest

from _mock_network import mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.california.adapter import CaliforniaAdapter
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

# --- REAL live official captures (Aug 27 2026), ViewState stubbed. ---
FIXTURES = Path(__file__).parent / "fixtures"

TOC_HTML = (FIXTURES / "ca_codes_toc.html").read_text(encoding="utf-8")
TREE_BPC_HTML = (FIXTURES / "ca_tree_bpc.html").read_text(encoding="utf-8")
DOC_311_HTML = (FIXTURES / "ca_doc_bpc_311.html").read_text(encoding="utf-8")
DOC_327_HTML = (FIXTURES / "ca_doc_bpc_327.html").read_text(encoding="utf-8")
DOC_4P3_HTML = (FIXTURES / "ca_doc_bpc_4p3.html").read_text(encoding="utf-8")
DOC_GP_HTML = (FIXTURES / "ca_doc_bpc_gp.html").read_text(encoding="utf-8")
DOC_DIV6_HTML = (FIXTURES / "ca_doc_bpc_div6.html").read_text(encoding="utf-8")

SEC_BPC_5000 = (FIXTURES / "ca_section_bpc_5000.html").read_text(encoding="utf-8")
SEC_BPC_5025_3 = (FIXTURES / "ca_section_bpc_5025.3.html").read_text(encoding="utf-8")
SEC_CIV_43_3 = (FIXTURES / "ca_section_civ_43.3.html").read_text(encoding="utf-8")
SEC_CIV_1624 = (FIXTURES / "ca_section_civ_1624.html").read_text(encoding="utf-8")
SEC_PEN_187 = (FIXTURES / "ca_section_pen_187.html").read_text(encoding="utf-8")
SEC_VEH_23152 = (FIXTURES / "ca_section_veh_23152.html").read_text(encoding="utf-8")
SEC_GOV_12940 = (FIXTURES / "ca_section_gov_12940.html").read_text(encoding="utf-8")
SEC_WIC_5325 = (FIXTURES / "ca_section_wic_5325.html").read_text(encoding="utf-8")
SEC_INVALID = (FIXTURES / "ca_section_invalid.html").read_text(encoding="utf-8")
SEC_REPEALED = (FIXTURES / "ca_section_repealed.html").read_text(encoding="utf-8")

BASE = "https://leginfo.legislature.ca.gov/faces"
TOC_URL = f"{BASE}/codesTOC.xhtml"
TREE_BPC_URL = f"{BASE}/codedisplayexpand.xhtml?tocCode=BPC"


def _doc_url(code: str, division: str, part: str, chapter: str, article: str) -> str:
    return (
        f"{BASE}/codes_displayText.xhtml?lawCode={code}&division={division}"
        f"&title=&part={part}&chapter={chapter}&article={article}"
    )


def _sec_url(code: str, section: str) -> str:
    return f"{BASE}/codes_displaySection.xhtml?lawCode={code}&sectionNum={section}"


def _bpc_ref(identifier: str) -> SectionRef:
    return SectionRef(
        chapter=ChapterRef(
            title=TitleRef(state_code="CA", identifier="BPC"),
            identifier="3//1/1",
        ),
        identifier=identifier,
    )


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert CaliforniaAdapter.__abstractmethods__ == frozenset()
        adapter = CaliforniaAdapter()
        assert adapter.state_code == "CA"
        assert adapter.state_name == "California"


class TestValidation:
    def setup_method(self) -> None:
        self.adapter = CaliforniaAdapter()

    def test_valid_code_normalized(self) -> None:
        assert self.adapter._valid_code("BPC") == "BPC"

    def test_lowercase_code_upper_cased(self) -> None:
        assert self.adapter._valid_code("bpc") == "BPC"

    def test_constitution_code_rejected(self) -> None:
        with pytest.raises(RefNotFoundError):
            self.adapter._valid_code("CONS")

    def test_non_alphabetic_code_rejected(self) -> None:
        with pytest.raises(RefNotFoundError):
            self.adapter._valid_code("123")

    def test_overlong_code_rejected(self) -> None:
        with pytest.raises(RefNotFoundError):
            self.adapter._valid_code("ABCDE")

    def test_canonical_section_strips_leading_zeros(self) -> None:
        assert self.adapter._canonical_section("05000") == "5000"

    def test_canonical_section_keeps_decimal(self) -> None:
        assert self.adapter._canonical_section("5025.3") == "5025.3"

    def test_canonical_section_keeps_integer(self) -> None:
        assert self.adapter._canonical_section("5000") == "5000"

    def test_canonical_section_rejects_lettered(self) -> None:
        assert self.adapter._canonical_section("1A") is None

    def test_canonical_section_rejects_alpha(self) -> None:
        assert self.adapter._canonical_section("abc") is None

    def test_parse_chapter_article(self) -> None:
        assert self.adapter._parse_chapter("3//1/1") == ("3", "", "1", "1")

    def test_parse_chapter_general_provisions(self) -> None:
        assert self.adapter._parse_chapter("///") == ("", "", "", "")

    def test_parse_chapter_part(self) -> None:
        assert self.adapter._parse_chapter("4/3//") == ("4", "3", "", "")

    def test_parse_chapter_decimal_article(self) -> None:
        assert self.adapter._parse_chapter("3//1/1.5") == ("3", "", "1", "1.5")

    def test_parse_chapter_too_many_segments(self) -> None:
        with pytest.raises(RefNotFoundError):
            self.adapter._parse_chapter("3//1/1/9")

    def test_parse_chapter_non_numeric_segment(self) -> None:
        with pytest.raises(RefNotFoundError):
            self.adapter._parse_chapter("x//1/1")


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = CaliforniaAdapter()

    def test_title_ref_url_is_code_tree(self) -> None:
        ref = TitleRef(state_code="CA", identifier="BPC")
        assert self.adapter.build_url(ref) == TREE_BPC_URL

    def test_chapter_ref_url_is_document(self) -> None:
        ref = ChapterRef(
            title=TitleRef(state_code="CA", identifier="BPC"),
            identifier="3//1/1",
        )
        assert self.adapter.build_url(ref) == _doc_url("BPC", "3", "", "1", "1")

    def test_chapter_ref_general_provisions_url(self) -> None:
        ref = ChapterRef(
            title=TitleRef(state_code="CA", identifier="BPC"),
            identifier="///",
        )
        assert self.adapter.build_url(ref) == _doc_url("BPC", "", "", "", "")

    def test_section_ref_url(self) -> None:
        ref = _bpc_ref("5000")
        assert self.adapter.build_url(ref) == _sec_url("BPC", "5000")

    def test_section_ref_decimal_url(self) -> None:
        ref = _bpc_ref("5025.3")
        assert self.adapter.build_url(ref) == _sec_url("BPC", "5025.3")

    def test_section_ref_leading_zero_canonicalized(self) -> None:
        ref = _bpc_ref("05000")
        assert self.adapter.build_url(ref) == _sec_url("BPC", "5000")

    def test_invalid_code_raises_ref_not_found(self) -> None:
        ref = TitleRef(state_code="CA", identifier="123")
        with pytest.raises(RefNotFoundError):
            self.adapter.build_url(ref)

    def test_invalid_section_raises_ref_not_found(self) -> None:
        ref = _bpc_ref("abc")
        with pytest.raises(RefNotFoundError):
            self.adapter.build_url(ref)

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def setup_method(self) -> None:
        self.adapter = CaliforniaAdapter()

    def test_returns_all_statute_codes(self) -> None:
        with mock_urlopen_serving({TOC_URL: TOC_HTML}):
            titles = self.adapter.list_titles()

        identifiers = [t.identifier for t in titles]
        assert "BPC" in identifiers
        assert "CIV" in identifiers
        assert "PEN" in identifiers
        assert "VEH" in identifiers
        assert "WIC" in identifiers

    def test_excludes_constitution(self) -> None:
        with mock_urlopen_serving({TOC_URL: TOC_HTML}):
            titles = self.adapter.list_titles()

        assert all(t.identifier != "CONS" for t in titles)

    def test_title_names_populated(self) -> None:
        with mock_urlopen_serving({TOC_URL: TOC_HTML}):
            titles = self.adapter.list_titles()

        bpc = next(t for t in titles if t.identifier == "BPC")
        assert "Business and Professions Code" in bpc.name
        assert bpc.level == HierarchyLevel.TITLE

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        with mock_urlopen_serving({TOC_URL: "<html><body>no codes</body></html>"}):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()


class TestListChapters:
    def setup_method(self) -> None:
        self.adapter = CaliforniaAdapter()

    def test_returns_fetchable_documents(self) -> None:
        bpc = TitleRef(state_code="CA", identifier="BPC")
        with mock_urlopen_serving({TREE_BPC_URL: TREE_BPC_HTML}):
            chapters = self.adapter.list_chapters(bpc)

        assert len(chapters) > 900
        identifiers = {c.identifier for c in chapters}
        assert "3//1/1" in identifiers  # Division 3, Chapter 1, Article 1
        assert "///" in identifiers  # General Provisions
        assert "4/3//" in identifiers  # Division 4, Part 3
        assert "3//2.7/" in identifiers  # Chapter 2.7 with no article
        assert len(identifiers) == len(chapters)  # no duplicates

    def test_node_names_carried(self) -> None:
        bpc = TitleRef(state_code="CA", identifier="BPC")
        with mock_urlopen_serving({TREE_BPC_URL: TREE_BPC_HTML}):
            chapters = self.adapter.list_chapters(bpc)

        by_id = {c.identifier: c for c in chapters}
        assert by_id["3//1/1"].name == "ARTICLE 1. Administration"
        assert by_id["///"].name == "GENERAL PROVISIONS"

    def test_refs_are_chapter_refs(self) -> None:
        bpc = TitleRef(state_code="CA", identifier="BPC")
        with mock_urlopen_serving({TREE_BPC_URL: TREE_BPC_HTML}):
            chapters = self.adapter.list_chapters(bpc)

        assert all(isinstance(c.ref, ChapterRef) for c in chapters)
        assert all(c.level == HierarchyLevel.CHAPTER for c in chapters)

    def test_invalid_code_raises_ref_not_found(self) -> None:
        with pytest.raises(RefNotFoundError):
            self.adapter.list_chapters(TitleRef(state_code="CA", identifier="123"))

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(TitleRef(state_code="CA", identifier="BPC"))

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        with mock_urlopen_serving({TREE_BPC_URL: "<html>nothing</html>"}):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(TitleRef(state_code="CA", identifier="BPC"))


class TestListSections:
    def setup_method(self) -> None:
        self.adapter = CaliforniaAdapter()

    def _serve(self, url_to_html: dict[str, str]):
        return mock_urlopen_serving(url_to_html)

    def test_returns_sections_from_article_document(self) -> None:
        chapter = ChapterRef(
            title=TitleRef(state_code="CA", identifier="BPC"), identifier="3//1/1"
        )
        with self._serve({_doc_url("BPC", "3", "", "1", "1"): DOC_311_HTML}):
            sections = self.adapter.list_sections(chapter)

        identifiers = [s.identifier for s in sections]
        assert "5000" in identifiers
        assert "5000.1" in identifiers  # decimal section
        assert "5025.3" in identifiers  # decimal section (last)
        assert len(sections) == 32
        assert all(s.level == HierarchyLevel.SECTION for s in sections)

    def test_no_article_chapter_document(self) -> None:
        chapter = ChapterRef(
            title=TitleRef(state_code="CA", identifier="BPC"), identifier="3//2.7/"
        )
        with self._serve({_doc_url("BPC", "3", "", "2.7", ""): DOC_327_HTML}):
            sections = self.adapter.list_sections(chapter)

        assert [s.identifier for s in sections] == ["5499.30"]

    def test_part_level_document(self) -> None:
        chapter = ChapterRef(
            title=TitleRef(state_code="CA", identifier="BPC"), identifier="4/3//"
        )
        with self._serve({_doc_url("BPC", "4", "3", "", ""): DOC_4P3_HTML}):
            sections = self.adapter.list_sections(chapter)

        assert [s.identifier for s in sections] == ["11300", "11301"]

    def test_general_provisions_document(self) -> None:
        chapter = ChapterRef(
            title=TitleRef(state_code="CA", identifier="BPC"), identifier="///"
        )
        with self._serve({_doc_url("BPC", "", "", "", ""): DOC_GP_HTML}):
            sections = self.adapter.list_sections(chapter)

        assert sections and sections[0].identifier == "1"

    def test_empty_intermediate_document_returns_empty(self) -> None:
        chapter = ChapterRef(
            title=TitleRef(state_code="CA", identifier="BPC"), identifier="6///"
        )
        with self._serve({_doc_url("BPC", "6", "", "", ""): DOC_DIV6_HTML}):
            sections = self.adapter.list_sections(chapter)

        assert sections == ()

    def test_invalid_chapter_identifier_raises_ref_not_found(self) -> None:
        chapter = ChapterRef(
            title=TitleRef(state_code="CA", identifier="BPC"), identifier="x//1/1"
        )
        with pytest.raises(RefNotFoundError):
            self.adapter.list_sections(chapter)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        chapter = ChapterRef(
            title=TitleRef(state_code="CA", identifier="BPC"), identifier="3//1/1"
        )
        with mock_urlopen_error(urllib.error.URLError("simulated")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_sections(chapter)


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = CaliforniaAdapter()

    def test_full_retrieval_normal_section(self) -> None:
        with mock_urlopen_serving({_sec_url("BPC", "5000"): SEC_BPC_5000}):
            section = self.adapter.retrieve_section(_bpc_ref("5000"))

        assert section.ref.state_code == "CA"
        assert section.ref.identifier == "5000"
        assert section.citation.raw == "Cal. BPC § 5000"
        assert section.heading is None
        assert section.text.startswith(
            "(a) There is in the Department of Consumer Affairs"
        )
        assert section.status.value == "unknown"
        assert section.amendment_notes is not None
        assert "Amended by Stats. 2024" in section.amendment_notes
        assert section.source_url == _sec_url("BPC", "5000")
        assert section.retrieved_at is not None

    def test_decimal_section_retrieval(self) -> None:
        with mock_urlopen_serving({_sec_url("BPC", "5025.3"): SEC_BPC_5025_3}):
            section = self.adapter.retrieve_section(_bpc_ref("5025.3"))

        assert section.citation.raw == "Cal. BPC § 5025.3"
        assert section.text

    def test_cross_code_decimal_section(self) -> None:
        civ = TitleRef(state_code="CA", identifier="CIV")
        ref = SectionRef(
            chapter=ChapterRef(title=civ, identifier="2//1/1"),
            identifier="43.3",
        )
        with mock_urlopen_serving({_sec_url("CIV", "43.3"): SEC_CIV_43_3}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Cal. CIV § 43.3"
        assert section.text

    def test_cross_code_normal_section(self) -> None:
        civ = TitleRef(state_code="CA", identifier="CIV")
        ref = SectionRef(
            chapter=ChapterRef(title=civ, identifier="2//1/1"), identifier="1624"
        )
        with mock_urlopen_serving({_sec_url("CIV", "1624"): SEC_CIV_1624}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Cal. CIV § 1624"
        assert "invalid" in section.text

    def test_penal_code_section(self) -> None:
        pen = TitleRef(state_code="CA", identifier="PEN")
        ref = SectionRef(
            chapter=ChapterRef(title=pen, identifier="9//1/1"), identifier="187"
        )
        with mock_urlopen_serving({_sec_url("PEN", "187"): SEC_PEN_187}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Cal. PEN § 187"
        assert section.text

    def test_vehicle_code_section(self) -> None:
        veh = TitleRef(state_code="CA", identifier="VEH")
        ref = SectionRef(
            chapter=ChapterRef(title=veh, identifier="7//1/1"), identifier="23152"
        )
        with mock_urlopen_serving({_sec_url("VEH", "23152"): SEC_VEH_23152}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Cal. VEH § 23152"
        assert section.text

    def test_government_code_section(self) -> None:
        gov = TitleRef(state_code="CA", identifier="GOV")
        ref = SectionRef(
            chapter=ChapterRef(title=gov, identifier="9//1/1"), identifier="12940"
        )
        with mock_urlopen_serving({_sec_url("GOV", "12940"): SEC_GOV_12940}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Cal. GOV § 12940"
        assert section.text

    def test_welfare_code_section(self) -> None:
        wic = TitleRef(state_code="CA", identifier="WIC")
        ref = SectionRef(
            chapter=ChapterRef(title=wic, identifier="9//1/1"), identifier="5325"
        )
        with mock_urlopen_serving({_sec_url("WIC", "5325"): SEC_WIC_5325}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Cal. WIC § 5325"
        assert section.text

    def test_invalid_section_raises_ref_not_found(self) -> None:
        with mock_urlopen_serving({_sec_url("BPC", "999999"): SEC_INVALID}):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(_bpc_ref("999999"))

    def test_repealed_removed_section_raises_ref_not_found(self) -> None:
        pen = TitleRef(state_code="CA", identifier="PEN")
        ref = SectionRef(
            chapter=ChapterRef(title=pen, identifier="9//1/1"), identifier="12020"
        )
        with mock_urlopen_serving({_sec_url("PEN", "12020"): SEC_REPEALED}):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(ref)

    def test_lettered_section_raises_ref_not_found(self) -> None:
        with pytest.raises(RefNotFoundError):
            self.adapter.retrieve_section(_bpc_ref("1A"))

    def test_alpha_section_raises_ref_not_found(self) -> None:
        with pytest.raises(RefNotFoundError):
            self.adapter.retrieve_section(_bpc_ref("abc"))

    def test_leading_zero_section_canonicalized(self) -> None:
        with mock_urlopen_serving({_sec_url("BPC", "5000"): SEC_BPC_5000}):
            section = self.adapter.retrieve_section(_bpc_ref("05000"))

        assert section.ref.identifier == "5000"
        assert section.citation.raw == "Cal. BPC § 5000"

    def test_lowercase_code_accepted(self) -> None:
        lower = TitleRef(state_code="CA", identifier="bpc")
        ref = SectionRef(
            chapter=ChapterRef(title=lower, identifier="3//1/1"), identifier="5000"
        )
        with mock_urlopen_serving({_sec_url("BPC", "5000"): SEC_BPC_5000}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Cal. BPC § 5000"

    def test_wrong_code_raises_ref_mismatch(self) -> None:
        civ = TitleRef(state_code="CA", identifier="CIV")
        ref = SectionRef(
            chapter=ChapterRef(title=civ, identifier="2//1/1"), identifier="5000"
        )
        # The BPC 5000 fixture declares code BPC, requested CIV.
        with mock_urlopen_serving({_sec_url("CIV", "5000"): SEC_BPC_5000}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(ref)

    def test_wrong_section_raises_ref_mismatch(self) -> None:
        with mock_urlopen_serving({_sec_url("BPC", "5001"): SEC_BPC_5000}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(_bpc_ref("5001"))

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(_bpc_ref("5000"))

    def test_empty_page_raises_ref_not_found(self) -> None:
        with mock_urlopen_serving({_sec_url("BPC", "5000"): "<html></html>"}):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(_bpc_ref("5000"))

    def test_malformed_content_block_raises_normalization_error(self) -> None:
        # A content block with no font block / no declared section.
        malformed = (
            '<div id="codeLawSectionNoHead"><div align="left">'
            "<h4><b>Business and Professions Code - BPC</b></h4></div>"
            "</div></div></BODY></HTML>"
        )
        with mock_urlopen_serving({_sec_url("BPC", "5000"): malformed}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(_bpc_ref("5000"))


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = CaliforniaAdapter()

    def test_normalize_success(self) -> None:
        ref = _bpc_ref("5000")
        parsed = ParsedDocument(
            raw_citation="Cal. BPC § 5000",
            text="(a) Body text here.",
            source_url=_sec_url("BPC", "5000"),
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref is ref
        assert section.citation.raw == "Cal. BPC § 5000"
        assert section.text == "(a) Body text here."
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="WA", identifier="49"),
                identifier="60",
            ),
            identifier="49.60.010",
        )
        parsed = ParsedDocument(raw_citation="Cal. BPC § 5000", text="x")
        with pytest.raises(NormalizationError):
            self.adapter.normalize(parsed, ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _bpc_ref("5001")
        parsed = ParsedDocument(raw_citation="Cal. BPC § 5000", text="x")
        with pytest.raises(RefMismatchError):
            self.adapter.normalize(parsed, ref)


class TestHierarchyMapping:
    def test_title_chapter_section_chain_descends(self) -> None:
        title = TitleRef(state_code="CA", identifier="BPC")
        chapter = ChapterRef(title=title, identifier="3//1/1")
        section = SectionRef(chapter=chapter, identifier="5000")

        assert chapter.state_code == "CA"
        assert section.state_code == "CA"
        assert chapter.title is title
        assert section.chapter is chapter