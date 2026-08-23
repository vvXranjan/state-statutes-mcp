"""Tests for KentuckyAdapter.

The Kentucky Revised Statutes (apps.legislature.ky.gov) is the framework's
first PDF-family source: discovery is server-rendered HTML (a statutes
index page listing all titles and chapters, and a chapter page listing
sections), while each section is a real PDF document retrieved through the
shared ``fetch_bytes`` + ``extract_pdf_text`` infrastructure.

``TitleRef.identifier`` is the Roman-numeral title (``"XVII"``),
``ChapterRef.identifier`` is the chapter number (``"205"``), and
``SectionRef.identifier`` is the full KRS citation (``"205.010"``). The
site's opaque per-chapter and per-section IDs are resolved adapter-internally
from the index and chapter pages and never leak into the refs.

**DANGEROUS host behavior (VERIFIED)**: ``chapter.aspx``/``statute.aspx``
return HTTP 200 with a fallback page (the index) for bad IDs instead of a
clean HTTP 404. The adapter therefore (1) never trusts the requested
chapter number -- it requires the fetched chapter page to declare that
chapter, and (2) treats a non-PDF response to a section fetch as not-found.

**REAL live fixtures**: the ``ky_*`` fixtures are verbatim captures of the
official host fetched live on Aug 23 2026 (see ``docs/research/kentucky.md``);
they are NOT synthetic. The chapter pages and index are HTML; the section
fixtures are real PDF documents.

Network tests mock the real network boundary
(``urllib.request.urlopen`` as imported by the shared ``_fetch`` helper),
never adapter internals. PDF fixtures are served as raw bytes via
``mock_urlopen_serving_bytes``.
"""

from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest

from _mock_network import mock_urlopen_error, mock_urlopen_serving_bytes

from state_statutes_mcp.adapters.kentucky.adapter import KentuckyAdapter
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
# --- (apps.legislature.ky.gov, fetched Aug 23 2026; see docs/research/kentucky.md).
FIXTURES = Path(__file__).parent / "fixtures"

INDEX_HTML = (FIXTURES / "ky_index.html").read_bytes()
CH205_HTML = (FIXTURES / "ky_chapter205.html").read_bytes()
CH367_HTML = (FIXTURES / "ky_chapter367.html").read_bytes()
INVALID_SECTION_HTML = (FIXTURES / "ky_invalid_section.html").read_bytes()
SEC205_010_PDF = (FIXTURES / "ky_section_205-010.pdf").read_bytes()
SEC205_020_PDF = (FIXTURES / "ky_section_205-020.pdf").read_bytes()
SEC205_045_PDF = (FIXTURES / "ky_section_205-045.pdf").read_bytes()
SEC367_110_PDF = (FIXTURES / "ky_section_367-110.pdf").read_bytes()

BASE = "https://apps.legislature.ky.gov/LAW/STATUTES"
INDEX_URL = f"{BASE}/"
CH205_URL = f"{BASE}/chapter.aspx?id=38124"
CH367_URL = f"{BASE}/chapter.aspx?id=39092"
SEC205_010_URL = f"{BASE}/statute.aspx?id=7624"
SEC205_020_URL = f"{BASE}/statute.aspx?id=7625"
SEC205_045_URL = f"{BASE}/statute.aspx?id=7628"
SEC367_110_URL = f"{BASE}/statute.aspx?id=34907"


def _title_ref(identifier: str = "XVII") -> TitleRef:
    return TitleRef(state_code="KY", identifier=identifier)


def _chapter_ref(title: str = "XVII", chapter: str = "205") -> ChapterRef:
    return ChapterRef(title=_title_ref(title), identifier=chapter)


def _make_ref(chapter: str = "205", section: str = "205.010") -> SectionRef:
    return SectionRef(chapter=_chapter_ref(chapter=chapter), identifier=section)


def _serve_all() -> dict[str, bytes]:
    """Serve every fixture used by the discovery + retrieval tests."""
    return {
        INDEX_URL: INDEX_HTML,
        CH205_URL: CH205_HTML,
        CH367_URL: CH367_HTML,
        SEC205_010_URL: SEC205_010_PDF,
        SEC205_020_URL: SEC205_020_PDF,
        SEC205_045_URL: SEC205_045_PDF,
        SEC367_110_URL: SEC367_110_PDF,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert KentuckyAdapter.__abstractmethods__ == frozenset()
        adapter = KentuckyAdapter()
        assert adapter.state_code == "KY"
        assert adapter.state_name == "Kentucky"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = KentuckyAdapter()

    def test_title_ref_url_is_index(self) -> None:
        assert self.adapter.build_url(_title_ref()) == INDEX_URL

    def test_chapter_ref_url_resolves_opaque_id(self) -> None:
        with mock_urlopen_serving_bytes({INDEX_URL: INDEX_HTML}):
            assert self.adapter.build_url(_chapter_ref()) == CH205_URL

    def test_section_ref_url_resolves_opaque_id(self) -> None:
        served = {INDEX_URL: INDEX_HTML, CH205_URL: CH205_HTML}
        with mock_urlopen_serving_bytes(served):
            assert self.adapter.build_url(_make_ref()) == SEC205_010_URL

    def test_unknown_chapter_raises_ref_not_found(self) -> None:
        # A chapter number absent from the index cannot be resolved.
        ref = _chapter_ref(chapter="9999")
        with mock_urlopen_serving_bytes({INDEX_URL: INDEX_HTML}):
            with pytest.raises(RefNotFoundError, match="not listed"):
                self.adapter.build_url(ref)

    def test_unknown_section_raises_ref_not_found(self) -> None:
        # A section citation absent from the chapter page cannot be
        # resolved, even though the chapter itself resolves fine.
        served = {INDEX_URL: INDEX_HTML, CH205_URL: CH205_HTML}
        ref = _make_ref(section="205.9999")
        with mock_urlopen_serving_bytes(served):
            with pytest.raises(RefNotFoundError, match="not listed"):
                self.adapter.build_url(ref)

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def test_returns_all_44_titles(self) -> None:
        adapter = KentuckyAdapter()
        with mock_urlopen_serving_bytes({INDEX_URL: INDEX_HTML}):
            titles = adapter.list_titles()

        assert len(titles) == 44
        assert all(t.level == HierarchyLevel.TITLE for t in titles)
        assert all(t.ref.state_code == "KY" for t in titles)
        assert titles[0].identifier == "I"
        assert titles[0].name == "SOVEREIGNTY AND JURISDICTION OF THE COMMONWEALTH"
        assert titles[-1].identifier == "LI"
        assert titles[-1].name == "UNIFIED JUVENILE CODE"

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = KentuckyAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_titles()

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = KentuckyAdapter()
        with mock_urlopen_serving_bytes({INDEX_URL: b"<html></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable title"):
                adapter.list_titles()


class TestListChapters:
    def test_returns_chapters_under_title(self) -> None:
        adapter = KentuckyAdapter()
        with mock_urlopen_serving_bytes({INDEX_URL: INDEX_HTML}):
            chapters = adapter.list_chapters(_title_ref("XVII"))

        # Title XVII (Economic Security and Public Welfare) holds 31
        # chapters including 205.
        assert [c.identifier for c in chapters].count("205") == 1
        ch205 = next(c for c in chapters if c.identifier == "205")
        assert ch205.name == "PUBLIC ASSISTANCE AND MEDICAL ASSISTANCE"
        assert all(c.level == HierarchyLevel.CHAPTER for c in chapters)
        assert all(c.ref.title == _title_ref("XVII") for c in chapters)

    def test_unknown_title_raises_ref_not_found(self) -> None:
        adapter = KentuckyAdapter()
        with mock_urlopen_serving_bytes({INDEX_URL: INDEX_HTML}):
            with pytest.raises(RefNotFoundError, match="not listed"):
                adapter.list_chapters(_title_ref("NOTATITLE"))

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = KentuckyAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_chapters(_title_ref("XVII"))


class TestListSections:
    def test_returns_sections_for_chapter(self) -> None:
        adapter = KentuckyAdapter()
        chapter = _chapter_ref()
        served = {INDEX_URL: INDEX_HTML, CH205_URL: CH205_HTML}
        with mock_urlopen_serving_bytes(served):
            sections = adapter.list_sections(chapter)

        ids = [s.identifier for s in sections]
        assert "205.010" in ids and "205.020" in ids and "205.990" in ids
        assert len(ids) == len(set(ids))
        s010 = next(s for s in sections if s.identifier == "205.010")
        assert s010.name == "Definitions for chapter."
        assert all(s.level == HierarchyLevel.SECTION for s in sections)
        assert all(s.ref.chapter == chapter for s in sections)

    def test_chapter_mismatch_raises_ref_mismatch_error(self) -> None:
        # The chapter-ID safety: even when the requested chapter resolves
        # to an opaque ID, the fetched page must declare that chapter. Here
        # the (real) 205 page is doctored to declare "KRS Chapter 999" so
        # the mismatch is detected.
        adapter = KentuckyAdapter()
        doctored = CH205_HTML.replace(
            b'<span id="Banner1_lblPageTitle">KRS Chapter 205</span>',
            b'<span id="Banner1_lblPageTitle">KRS Chapter 999</span>',
        )
        served = {INDEX_URL: INDEX_HTML, CH205_URL: doctored}
        with mock_urlopen_serving_bytes(served):
            with pytest.raises(RefMismatchError, match="does not match"):
                adapter.list_sections(_chapter_ref(chapter="205"))

    def test_unknown_chapter_raises_ref_not_found(self) -> None:
        adapter = KentuckyAdapter()
        chapter = _chapter_ref(chapter="9999")
        with mock_urlopen_serving_bytes({INDEX_URL: INDEX_HTML}):
            with pytest.raises(RefNotFoundError, match="not listed"):
                adapter.list_sections(chapter)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = KentuckyAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_sections(_chapter_ref())


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = KentuckyAdapter()

    def test_full_retrieval_normal_section(self) -> None:
        ref = _make_ref()
        with mock_urlopen_serving_bytes(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "KRS 205.010"
        assert section.citation.state_code == "KY"
        assert section.ref == ref
        assert section.heading == "Definitions for chapter."
        assert section.text.startswith(
            "As used in this chapter, unless the context requires otherwise"
        )
        assert "(1) \"Cabinet\" means" in section.text
        assert section.status.value == "unknown"
        assert section.amendment_notes.startswith(
            "Effective: June 20, 2005\nHistory: Amended 2005 Ky."
        )
        assert section.source_url == SEC205_010_URL
        assert section.retrieved_at is not None

    def test_repealed_section_empty_body_with_history(self) -> None:
        ref = _make_ref(section="205.020")
        with mock_urlopen_serving_bytes(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "KRS 205.020"
        assert section.heading == "Repealed, 1950."
        assert section.text == ""
        assert section.status.value == "unknown"
        assert section.amendment_notes.startswith("Catchline at repeal:")
        assert "History: Repealed 1950 Ky. Acts ch. 110" in section.amendment_notes

    def test_renumbered_section_empty_body_with_note(self) -> None:
        ref = _make_ref(section="205.045")
        with mock_urlopen_serving_bytes(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "KRS 205.045"
        assert section.heading == "Renumbered as 45.235, effective 1948."
        assert section.text == ""
        assert section.status.value == "unknown"
        assert section.amendment_notes.startswith("Note:  1948 Ky. Acts ch. 236")

    def test_cross_chapter_section_retrieval(self) -> None:
        # Chapter 367 is under Title XXIX; its sections are resolved via
        # its own chapter page.
        ref = _make_ref(chapter="367", section="367.110")
        served = {
            INDEX_URL: INDEX_HTML,
            CH367_URL: CH367_HTML,
            SEC367_110_URL: SEC367_110_PDF,
        }
        with mock_urlopen_serving_bytes(served):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "KRS 367.110"
        assert section.heading == "Definitions."
        assert section.text.startswith("As used in KRS 367.170 to 367.300")
        assert section.source_url == SEC367_110_URL

    def test_invalid_section_non_pdf_raises_ref_not_found(self) -> None:
        # VERIFIED: a bad section ID returns HTTP 200 with the index page
        # (not a PDF). Request a resolvable section (205.010 -> opaque ID
        # 7624) but serve the non-PDF fallback under that URL; the adapter
        # must treat a non-PDF response to a section fetch as not-found.
        ref = _make_ref(section="205.010")
        served = {
            INDEX_URL: INDEX_HTML,
            CH205_URL: CH205_HTML,
            SEC205_010_URL: INVALID_SECTION_HTML,
        }
        with mock_urlopen_serving_bytes(served):
            with pytest.raises(RefNotFoundError, match="non-PDF"):
                self.adapter.retrieve_section(ref)

    def test_section_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        # The PDF's own declared citation must equal the requested section.
        # Request section 205.010 (which resolves to opaque ID 7624) but
        # serve the *205.020* PDF under that URL, so the extracted PDF
        # declares "205.020" and disagrees with the requested "205.010".
        ref = _make_ref(section="205.010")
        served = {
            INDEX_URL: INDEX_HTML,
            CH205_URL: CH205_HTML,
            SEC205_010_URL: SEC205_020_PDF,
        }
        with mock_urlopen_serving_bytes(served):
            with pytest.raises(RefMismatchError, match="does not match"):
                self.adapter.retrieve_section(ref)

    def test_malformed_pdf_raises_adapter_unavailable(self) -> None:
        # A section fetch that returns PDF-looking bytes that are not a
        # parseable PDF maps to AdapterUnavailableError via extract_pdf_text.
        ref = _make_ref()
        served = {
            INDEX_URL: INDEX_HTML,
            CH205_URL: CH205_HTML,
            SEC205_010_URL: b"%PDF-1.4 garbage not a real pdf",
        }
        with mock_urlopen_serving_bytes(served):
            with pytest.raises(AdapterUnavailableError, match="Could not extract"):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        ref = _make_ref()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestParseSectionText:
    def test_normal_section_parses_citation_catchline_body_notes(self) -> None:
        text = (
            "205.010   Definitions for chapter.\n"
            "As used in this chapter, unless the context requires otherwise:\n"
            "(1) \"Cabinet\" means the Cabinet.\n"
            "Effective: June 20, 2005\n"
            "History: Amended 2005 Ky. Acts ch. 99, sec. 51.\n"
        )
        citation, catchline, body, notes = KentuckyAdapter._parse_section_text(text)
        assert citation == "205.010"
        assert catchline == "Definitions for chapter."
        assert body == (
            "As used in this chapter, unless the context requires otherwise:\n"
            "(1) \"Cabinet\" means the Cabinet."
        )
        assert notes == (
            "Effective: June 20, 2005\nHistory: Amended 2005 Ky. Acts ch. 99, sec. 51."
        )

    def test_repealed_section_parses_empty_body(self) -> None:
        text = (
            "205.020   Repealed, 1950.\n"
            "Catchline at repeal:  Persons eligible for state assistance.\n"
            "History: Repealed 1950 Ky. Acts ch. 110, sec. 12.\n"
        )
        citation, catchline, body, notes = KentuckyAdapter._parse_section_text(text)
        assert citation == "205.020"
        assert catchline == "Repealed, 1950."
        assert body == ""
        assert notes.startswith("Catchline at repeal:")
        assert "History: Repealed 1950" in notes

    def test_malformed_text_raises_normalization_error(self) -> None:
        with pytest.raises(NormalizationError, match="no citation line"):
            KentuckyAdapter._parse_section_text("just some text with no citation")


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = KentuckyAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref()
        parsed = ParsedDocument(
            raw_citation="KRS 205.010",
            heading="Definitions for chapter.",
            text="As used in this chapter ...",
            amendment_notes="History: Amended 2005 Ky. Acts ch. 99.",
            source_url=SEC205_010_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "KRS 205.010"
        assert section.citation.state_code == "KY"
        assert section.heading == "Definitions for chapter."
        assert section.status.value == "unknown"
        assert section.amendment_notes == "History: Amended 2005 Ky. Acts ch. 99."

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="NV", identifier="XVII"),
                identifier="205",
            ),
            identifier="205.010",
        )
        parsed = ParsedDocument(raw_citation="KRS 205.010", text="Some text.")
        with pytest.raises(NormalizationError, match="expected 'KY'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref()
        parsed = ParsedDocument(raw_citation="KRS 205.999", text="Some text.")
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)


class TestHierarchyMapping:
    def test_title_chapter_section_chain_descends(self) -> None:
        # Title -> Chapter -> Section with opaque IDs resolved internally.
        adapter = KentuckyAdapter()
        with mock_urlopen_serving_bytes(_serve_all()):
            titles = adapter.list_titles()
            title = next(t.ref for t in titles if t.identifier == "XVII")
            assert isinstance(title, TitleRef)
            assert title.state_code == "KY"

            chapters = adapter.list_chapters(title)
            assert all(c.ref.title == title for c in chapters)
            chapter = next(c.ref for c in chapters if c.identifier == "205")
            assert isinstance(chapter, ChapterRef)
            assert chapter.title == title

            sections = adapter.list_sections(chapter)
            assert all(s.ref.chapter.title == title for s in sections)
            assert all(s.ref.chapter == chapter for s in sections)

            section = next(s.ref for s in sections if s.identifier == "205.010")
            retrieved = adapter.retrieve_section(section)
            assert retrieved.citation.raw == "KRS 205.010"
            assert retrieved.heading == "Definitions for chapter."